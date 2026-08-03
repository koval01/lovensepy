import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { api, eventsUrl } from "@/lib/api";
import { getClientId } from "@/lib/client-id";
import type { LinkStatus, ServiceState, ViewerRole } from "@/lib/types";
import {
  decodeServerEvent,
  encodeEcho,
  encodePresence,
  encodeRefresh,
  encodeRtt,
} from "@/lib/ws-codec";

/** No message (state or heartbeat) for this long means the socket is dead. */
const STALE_AFTER_MS = 26_000;
const WATCHDOG_EVERY_MS = 4_000;
const POLL_EVERY_MS = 1_500;
const RECONNECT_MIN_MS = 500;
const RECONNECT_MAX_MS = 15_000;
/** Host→remote→host application RTT probe interval. */
const ECHO_EVERY_MS = 2_000;

interface ServiceContextValue {
  state: ServiceState | null;
  status: LinkStatus;
  error: string | null;
  lastUpdatedAt: number | null;
  role: ViewerRole | null;
  clientId: string;
  /** Live browser↔browser RTT (ms), keyed by remote client id. */
  rttByPeer: Record<string, number>;
  /** Pull a snapshot now; `fresh` bypasses the server-side toy cache. */
  refresh: (fresh?: boolean) => Promise<ServiceState | null>;
  reportPresence: (patch: { tab?: string; activity?: string }) => void;
}

const ServiceContext = createContext<ServiceContextValue | null>(null);

function backoffDelay(attempt: number) {
  const base = Math.min(RECONNECT_MAX_MS, RECONNECT_MIN_MS * 2 ** attempt);
  return base / 2 + Math.random() * (base / 2);
}

/**
 * Keeps one live view of the service for the whole app.
 *
 * Transport strategy: a WebSocket pushes snapshots; if it cannot be opened or dies
 * (phone sleeping, Wi-Fi roam, proxy killing idle upgrades), the hook silently falls
 * back to polling and keeps retrying the socket in the background. Everything is
 * automatic, so the user never sees a "reconnect" button.
 *
 * Host browsers also run an echo probe through the service so the RTT shown is the
 * real round-trip from this tab to the remote controller's tab and back.
 */
export function ServiceProvider({ children }: { children: ReactNode }) {
  const clientId = useMemo(() => getClientId(), []);
  const [state, setState] = useState<ServiceState | null>(null);
  const [status, setStatus] = useState<LinkStatus>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  const [role, setRole] = useState<ViewerRole | null>(null);
  const [rttByPeer, setRttByPeer] = useState<Record<string, number>>({});

  const socketRef = useRef<WebSocket | null>(null);
  const pollTimerRef = useRef<number | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const echoTimerRef = useRef<number | null>(null);
  const attemptRef = useRef(0);
  const lastMessageRef = useRef(0);
  const stoppedRef = useRef(false);
  const inFlightRef = useRef<AbortController | null>(null);
  const revRef = useRef(-1);
  const roleRef = useRef<ViewerRole | null>(null);
  const pendingEchoRef = useRef<Map<string, { t0: number; peerId: string }>>(new Map());
  const presenceTabRef = useRef<string | null>(null);

  const applyState = useCallback((next: ServiceState) => {
    // Out-of-order delivery: a slow poll response can land after a newer push.
    if (next.rev < revRef.current) return;
    revRef.current = next.rev;
    setState(next);
    setLastUpdatedAt(Date.now());
    setError(null);
    const nextRole = next.presence?.self?.role ?? null;
    if (nextRole && nextRole !== roleRef.current) {
      roleRef.current = nextRole;
      setRole(nextRole);
    }
  }, []);

  const fetchState = useCallback(
    async (fresh = false) => {
      inFlightRef.current?.abort();
      const controller = new AbortController();
      inFlightRef.current = controller;
      try {
        const next = await api.state({ signal: controller.signal, fresh });
        applyState(next);
        return next;
      } catch (cause) {
        if (cause instanceof DOMException && cause.name === "AbortError") return null;
        setError(cause instanceof Error ? cause.message : "Cannot reach the service.");
        setStatus((current) => (current === "live" ? current : "offline"));
        return null;
      } finally {
        if (inFlightRef.current === controller) inFlightRef.current = null;
      }
    },
    [applyState],
  );

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current !== null) {
      window.clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const sendBytes = useCallback((payload: Uint8Array) => {
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(payload);
    }
  }, []);

  const reportPresence = useCallback(
    (patch: { tab?: string; activity?: string }) => {
      if (patch.tab) presenceTabRef.current = patch.tab;
      sendBytes(
        encodePresence({
          tab: patch.tab ?? presenceTabRef.current ?? undefined,
          activity: patch.activity,
        }),
      );
    },
    [sendBytes],
  );

  const handleEcho = useCallback(
    (kind: "echo" | "echo_reply", echo: { id: string; t0: number; t1?: number; fromId: string }) => {
      if (kind === "echo") {
        // Remote (or host answering a stray probe): bounce immediately.
        sendBytes(
          encodeEcho({
            id: echo.id,
            t0: echo.t0,
            t1: performance.now(),
            to: echo.fromId,
            reply: true,
          }),
        );
        return;
      }
      const id = String(echo.id ?? "");
      const pending = pendingEchoRef.current.get(id);
      if (!pending) return;
      pendingEchoRef.current.delete(id);
      const rtt = Math.max(0, performance.now() - pending.t0);
      const peerId = echo.fromId || pending.peerId;
      setRttByPeer((current) => ({ ...current, [peerId]: rtt }));
      sendBytes(encodeRtt(peerId, rtt));
    },
    [sendBytes],
  );

  const remotesRef = useRef<string[]>([]);

  const applyStateWithRemotes = useCallback(
    (next: ServiceState) => {
      applyState(next);
      remotesRef.current = (next.presence?.remotes ?? [])
        .filter((row) => row.online)
        .map((row) => row.client_id);
    },
    [applyState],
  );

  const stopPollingAndEcho = useCallback(() => {
    stopPolling();
    if (echoTimerRef.current !== null) {
      window.clearTimeout(echoTimerRef.current);
      echoTimerRef.current = null;
    }
  }, [stopPolling]);

  const scheduleEcho = useCallback(() => {
    if (echoTimerRef.current !== null || stoppedRef.current) return;
    const run = () => {
      echoTimerRef.current = null;
      if (stoppedRef.current) return;
      const socket = socketRef.current;
      if (socket?.readyState === WebSocket.OPEN && roleRef.current === "host") {
        for (const peerId of remotesRef.current) {
          const id = `${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
          const t0 = performance.now();
          pendingEchoRef.current.set(id, { t0, peerId });
          socket.send(encodeEcho({ id, t0, to: peerId }));
          window.setTimeout(() => pendingEchoRef.current.delete(id), 8_000);
        }
      }
      if (!stoppedRef.current) {
        echoTimerRef.current = window.setTimeout(run, ECHO_EVERY_MS);
      }
    };
    echoTimerRef.current = window.setTimeout(run, 400);
  }, []);

  const startPolling = useCallback(() => {
    if (pollTimerRef.current !== null || stoppedRef.current) return;
    const tick = async () => {
      pollTimerRef.current = null;
      if (stoppedRef.current || document.visibilityState === "hidden") return;
      const next = await fetchState();
      if (next) {
        remotesRef.current = (next.presence?.remotes ?? [])
          .filter((row) => row.online)
          .map((row) => row.client_id);
        setStatus((current) => (socketRef.current?.readyState === WebSocket.OPEN ? current : "polling"));
      }
      if (!stoppedRef.current && socketRef.current?.readyState !== WebSocket.OPEN) {
        pollTimerRef.current = window.setTimeout(tick, POLL_EVERY_MS);
      }
    };
    void tick();
  }, [fetchState]);

  const connect = useCallback(() => {
    if (stoppedRef.current) return;
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    const existing = socketRef.current;
    if (existing && (existing.readyState === WebSocket.OPEN || existing.readyState === WebSocket.CONNECTING)) {
      return;
    }

    let socket: WebSocket;
    try {
      socket = new WebSocket(eventsUrl());
      socket.binaryType = "arraybuffer";
    } catch {
      startPolling();
      scheduleReconnect();
      return;
    }
    socketRef.current = socket;

    socket.onopen = () => {
      attemptRef.current = 0;
      lastMessageRef.current = Date.now();
      setStatus("live");
      setError(null);
      stopPolling();
      socket.send(encodeRefresh());
      if (presenceTabRef.current) {
        socket.send(
          encodePresence({ tab: presenceTabRef.current, activity: "Connected" }),
        );
      }
      scheduleEcho();
    };

    socket.onmessage = (event) => {
      lastMessageRef.current = Date.now();
      void decodeServerEvent(event.data as ArrayBuffer | Blob | string).then((message) => {
        if (!message) return;
        if (message.type === "hello") {
          const nextRole = message.data.role as ViewerRole | "";
          if (nextRole === "host" || nextRole === "remote") {
            roleRef.current = nextRole;
            setRole(nextRole);
          }
          return;
        }
        if (message.type === "state") {
          applyStateWithRemotes(message.data);
          return;
        }
        if (message.type === "echo" || message.type === "echo_reply") {
          handleEcho(message.type, message.echo);
        }
      });
    };

    socket.onclose = () => {
      if (socketRef.current === socket) socketRef.current = null;
      if (stoppedRef.current) return;
      setStatus((current) => (current === "live" ? "polling" : current));
      startPolling();
      scheduleReconnect();
    };

    socket.onerror = () => {
      // `onclose` always follows; nothing to do here beyond letting it fire.
    };

    function scheduleReconnect() {
      if (stoppedRef.current || reconnectTimerRef.current !== null) return;
      const delay = backoffDelay(attemptRef.current++);
      reconnectTimerRef.current = window.setTimeout(() => {
        reconnectTimerRef.current = null;
        connect();
      }, delay);
    }
  }, [applyStateWithRemotes, handleEcho, scheduleEcho, startPolling, stopPolling]);

  const refresh = useCallback(
    async (fresh = false) => {
      const socket = socketRef.current;
      if (socket?.readyState === WebSocket.OPEN && !fresh) {
        socket.send(encodeRefresh());
      }
      return fetchState(fresh);
    },
    [fetchState],
  );

  useEffect(() => {
    stoppedRef.current = false;
    void fetchState(true);
    connect();

    const watchdog = window.setInterval(() => {
      if (stoppedRef.current || document.visibilityState === "hidden") return;
      const socket = socketRef.current;
      const stale = Date.now() - lastMessageRef.current > STALE_AFTER_MS;
      if (socket?.readyState === WebSocket.OPEN && stale) {
        socket.close();
      } else if (!socket) {
        connect();
      }
    }, WATCHDOG_EVERY_MS);

    const onVisible = () => {
      if (document.visibilityState !== "visible") {
        stopPollingAndEcho();
        return;
      }
      void fetchState(true);
      const socket = socketRef.current;
      if (socket?.readyState === WebSocket.OPEN) {
        lastMessageRef.current = Date.now();
        socket.send(encodeRefresh());
        scheduleEcho();
      } else {
        attemptRef.current = 0;
        connect();
      }
    };

    const onOnline = () => {
      attemptRef.current = 0;
      void fetchState(true);
      connect();
    };

    const onOffline = () => setStatus("offline");

    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    window.addEventListener("pageshow", onVisible);

    return () => {
      stoppedRef.current = true;
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("pageshow", onVisible);
      window.clearInterval(watchdog);
      stopPollingAndEcho();
      if (reconnectTimerRef.current !== null) window.clearTimeout(reconnectTimerRef.current);
      inFlightRef.current?.abort();
      const socket = socketRef.current;
      socketRef.current = null;
      socket?.close();
    };
  }, [connect, fetchState, scheduleEcho, stopPollingAndEcho]);

  // Drop RTT samples for peers that left.
  useEffect(() => {
    const alive = new Set(remotesRef.current);
    setRttByPeer((current) => {
      const next: Record<string, number> = {};
      for (const [id, value] of Object.entries(current)) {
        if (alive.has(id)) next[id] = value;
      }
      return next;
    });
  }, [state?.presence?.remotes]);

  const value = useMemo<ServiceContextValue>(
    () => ({
      state,
      status,
      error,
      lastUpdatedAt,
      role,
      clientId,
      rttByPeer,
      refresh,
      reportPresence,
    }),
    [state, status, error, lastUpdatedAt, role, clientId, rttByPeer, refresh, reportPresence],
  );

  return <ServiceContext.Provider value={value}>{children}</ServiceContext.Provider>;
}

export function useService() {
  const context = useContext(ServiceContext);
  if (!context) throw new Error("useService must be used inside <ServiceProvider>");
  return context;
}
