import { getClientId } from "@/lib/client-id";
import type {
  AccessCodeInfo,
  AutoConnectResult,
  NetworkInfo,
  PendingAccessApproval,
  ScanDevice,
  ServiceState,
  TaskRow,
  TunnelStatus,
} from "@/lib/types";

/** Sent on every REST call so the host can attribute activity to a remote browser. */
export const CLIENT_HEADER = "X-LovensePy-Client";

/** Rejected requests carry the HTTP status so callers can react (409 = transport off). */
export class ApiError extends Error {
  readonly status: number;
  readonly payload: unknown;

  constructor(message: string, status: number, payload?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

const DEFAULT_TIMEOUT_MS = 12_000;

/**
 * `AbortSignal.timeout` is missing on Safari < 16, which is still common on older
 * iPhones and iPads that cannot update. Compose signals manually there.
 */
function abortAfter(ms: number, external?: AbortSignal): { signal: AbortSignal; done: () => void } {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(new DOMException("Timeout", "TimeoutError")), ms);
  const onExternalAbort = () => controller.abort(external?.reason);
  if (external) {
    if (external.aborted) onExternalAbort();
    else external.addEventListener("abort", onExternalAbort, { once: true });
  }
  return {
    signal: controller.signal,
    done: () => {
      window.clearTimeout(timer);
      external?.removeEventListener("abort", onExternalAbort);
    },
  };
}

function describeError(status: number, body: unknown): string {
  if (typeof body === "string" && body.trim()) return body;
  if (body && typeof body === "object") {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      // FastAPI validation errors: [{loc: [...], msg: "..."}]
      const messages = detail
        .map((item) => {
          if (!item || typeof item !== "object") return null;
          const entry = item as { loc?: unknown[]; msg?: string };
          const where = Array.isArray(entry.loc) ? entry.loc.slice(1).join(".") : "";
          return where ? `${where}: ${entry.msg ?? "invalid"}` : (entry.msg ?? null);
        })
        .filter(Boolean);
      if (messages.length) return messages.join("; ");
    }
  }
  return `Request failed (HTTP ${status})`;
}

export interface RequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  options: RequestOptions = {},
): Promise<T> {
  const { signal, done } = abortAfter(options.timeoutMs ?? DEFAULT_TIMEOUT_MS, options.signal);
  try {
    const response = await fetch(path, {
      ...init,
      signal,
      headers: {
        Accept: "application/json",
        [CLIENT_HEADER]: getClientId(),
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(init.headers ?? {}),
      },
      // Same-origin cookies carry the external-access gate session after /auth/verify.
      credentials: "same-origin",
      cache: "no-store",
    });

    const text = await response.text();
    let body: unknown = null;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = text;
      }
    }
    if (!response.ok) {
      throw new ApiError(describeError(response.status, body), response.status, body);
    }
    return body as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "TimeoutError") {
      throw new ApiError("The service did not answer in time.", 0, error);
    }
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(
      error instanceof Error ? error.message : "Cannot reach the LovensePy service.",
      0,
      error,
    );
  } finally {
    done();
  }
}

const post = <T,>(path: string, body?: unknown, options?: RequestOptions) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }, options);

export interface FunctionCommandBody {
  toy_id: string;
  actions: Record<string, number>;
  time?: number;
  stop_previous?: boolean;
  loop_on_time?: number | null;
  loop_off_time?: number | null;
}

export interface PatternCommandBody {
  toy_id?: string | null;
  pattern?: number[];
  template?: string;
  actions?: string[] | null;
  interval?: number;
  time?: number;
}

export const api = {
  state: (options?: RequestOptions & { fresh?: boolean }) =>
    request<ServiceState>(`/state${options?.fresh ? "?fresh=true" : ""}`, {}, options),

  network: (options?: RequestOptions) => request<NetworkInfo>("/system/network", {}, options),

  tunnel: {
    status: (options?: RequestOptions) =>
      request<TunnelStatus>("/system/tunnel", {}, options),
    set: (enabled: boolean, port?: number) =>
      post<{ status: string; tunnel: TunnelStatus }>(
        "/system/tunnel",
        { enabled, ...(port ? { port } : {}) },
        // cloudflared can take ~15s to mint a trycloudflare URL
        { timeoutMs: 45_000 },
      ),
  },

  accessCode: {
    get: (options?: RequestOptions) =>
      request<AccessCodeInfo>("/system/access-code", {}, options),
    rotate: (options?: RequestOptions) =>
      post<AccessCodeInfo>("/system/access-code", undefined, options),
  },

  accessApprovals: {
    list: (options?: RequestOptions) =>
      request<{ approvals: PendingAccessApproval[] }>(
        "/system/access-approvals",
        {},
        options,
      ),
    allow: (requestId: string, options?: RequestOptions) =>
      post<{ status: string; request_id: string }>(
        `/system/access-approvals/${encodeURIComponent(requestId)}/allow`,
        undefined,
        options,
      ),
    deny: (requestId: string, options?: RequestOptions) =>
      post<{ status: string; request_id: string }>(
        `/system/access-approvals/${encodeURIComponent(requestId)}/deny`,
        undefined,
        options,
      ),
  },

  tasks: (options?: RequestOptions) => request<{ tasks: TaskRow[] }>("/tasks", {}, options),

  config: {
    setLanIp: (lan_ip: string, lan_port?: number) =>
      post<unknown>("/config/lan-ip", { lan_ip, ...(lan_port ? { lan_port } : {}) }),
    setSocket: (body: {
      developer_token: string;
      uid: string;
      platform: string;
      uname?: string | null;
    }) => post<unknown>("/config/socket", body),
    setBle: (body: {
      auto_reconnect?: boolean;
      advertisement_monitor?: boolean;
      scan_timeout_sec?: number;
      scan_name_prefix?: string;
      preset_uart_keyword?: string;
      preset_emulate_pattern?: boolean;
    }) => post<unknown>("/config/ble", body),
    setTransports: (body: { lan?: boolean; ble?: boolean; socket?: boolean }) =>
      post<unknown>("/config/transports", body),
  },

  command: {
    fn: (body: FunctionCommandBody, options?: RequestOptions) =>
      post<unknown>("/command/function", { time: 0, ...body }, options),
    preset: (body: { toy_id?: string | null; name: string; time?: number }) =>
      post<unknown>("/command/preset", { time: 0, ...body }),
    pattern: (body: PatternCommandBody) => post<unknown>("/command/pattern", { time: 0, ...body }),
    stopAll: (options?: RequestOptions) => post<unknown>("/command/stop/all", undefined, options),
    stopToy: (toy_id: string) => post<unknown>("/command/stop/toy", { toy_id }),
    stopFeature: (toy_id: string, feature: string, options?: RequestOptions) =>
      post<unknown>("/command/stop/feature", { toy_id, feature }, options),
    stopToys: (toy_ids: string[]) => post<unknown>("/command/stop/toys/batch", { toy_ids }),
  },

  ble: {
    scan: (timeout?: number) =>
      post<{ devices: ScanDevice[] }>(
        `/ble/scan${timeout ? `?timeout=${encodeURIComponent(timeout)}` : ""}`,
        undefined,
        // A scan blocks for its whole duration; allow for the slowest allowed timeout.
        { timeoutMs: ((timeout ?? 8) + 20) * 1000 },
      ),
    autoConnect: (body?: { timeout?: number; addresses?: string[]; include_registered?: boolean }) =>
      post<AutoConnectResult>("/ble/connect/auto", body ?? {}, {
        timeoutMs: ((body?.timeout ?? 8) + 60) * 1000,
      }),
    connect: (body: { address: string; name?: string | null; toy_type?: string | null }) =>
      post<{ toy_id: string }>("/ble/connect", body, { timeoutMs: 45_000 }),
    reconnect: (toyId: string) =>
      post<{ toy_id: string }>(`/ble/reconnect/${encodeURIComponent(toyId)}`, undefined, {
        timeoutMs: 45_000,
      }),
    disconnect: (toyId: string) =>
      post<unknown>(`/ble/disconnect/${encodeURIComponent(toyId)}`, undefined, { timeoutMs: 30_000 }),
    forget: (toyId: string) =>
      request<unknown>(
        `/ble/toys/${encodeURIComponent(toyId)}`,
        { method: "DELETE" },
        { timeoutMs: 30_000 },
      ),
  },

  socket: {
    requestQr: () => post<unknown>("/socket/qr/request"),
  },
};

/** WebSocket URL for `/ws` on the current origin (handles https → wss). */
export function eventsUrl(): string {
  const { protocol, host } = window.location;
  const scheme = protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${host}/ws?client_id=${encodeURIComponent(getClientId())}`;
}
