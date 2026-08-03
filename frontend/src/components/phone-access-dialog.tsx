import {
  Check,
  Copy,
  Globe,
  Loader2,
  RefreshCw,
  Smartphone,
  Wifi,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { QrCode } from "@/components/qr-code";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { useService } from "@/hooks/use-service";
import { api } from "@/lib/api";
import type { AccessCodeInfo, NetworkInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

type AccessMode = "local" | "tunnel";

/** Copy that works without the async clipboard API (http origins on older Safari). */
async function copyText(text: string) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall through to the legacy path below.
  }
  const field = document.createElement("textarea");
  field.value = text;
  field.setAttribute("readonly", "");
  field.style.position = "fixed";
  field.style.opacity = "0";
  document.body.appendChild(field);
  field.select();
  const ok = document.execCommand?.("copy") ?? false;
  document.body.removeChild(field);
  return ok;
}

function localTarget(info: NetworkInfo | null, currentUrl: string): string {
  if (info?.primary_url && !info.primary_url.includes("127.0.0.1") && !info.tunnel_url) {
    return info.primary_url;
  }
  const lan = info?.lan_urls.find((url) => !url.includes("127.0.0.1"));
  if (lan) return lan;
  if (info?.primary_url && !info.primary_url.includes("trycloudflare.com")) return info.primary_url;
  return currentUrl.includes("127.0.0.1") || currentUrl.includes("localhost")
    ? info?.lan_urls[0] || currentUrl
    : currentUrl;
}

function formatExpiry(sec: number | null | undefined) {
  if (sec == null) return null;
  const m = Math.floor(sec / 60);
  const s = Math.max(0, Math.round(sec % 60));
  if (m <= 0) return `${s}s left`;
  return `${m}m ${s.toString().padStart(2, "0")}s left`;
}

export function PhoneAccessDialog() {
  const { state, refresh } = useService();
  const tunnel = state?.tunnel;
  const [open, setOpen] = useState(false);
  const [info, setInfo] = useState<NetworkInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<"url" | "code" | null>(null);
  const [busy, setBusy] = useState(false);
  const [codeBusy, setCodeBusy] = useState(false);
  const [mode, setMode] = useState<AccessMode>("local");
  const [accessCode, setAccessCode] = useState<AccessCodeInfo | null>(null);

  const tunnelLive = Boolean(tunnel?.url);
  const tunnelStarting = Boolean(tunnel?.desired && !tunnel?.url);
  const missingBinary = tunnel != null && !tunnel.available;
  const gateEnabled = state?.gate?.enabled !== false;

  useEffect(() => {
    if (!open) return;
    let cancelled = false;

    const load = async () => {
      try {
        const next = await api.network();
        if (!cancelled) {
          setInfo(next);
          setError(null);
        }
        return next;
      } catch (cause: unknown) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Lookup failed");
        return null;
      }
    };

    void load();
    void refresh(true);

    const timer = window.setInterval(() => {
      void load();
      void refresh();
    }, 1500);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [open, refresh]);

  useEffect(() => {
    if (tunnelLive) setMode("tunnel");
  }, [tunnelLive]);

  const loadAccessCode = async (rotate = false) => {
    if (!gateEnabled) {
      setAccessCode({ status: "disabled", code: null, display: null, expires_in_sec: null });
      return;
    }
    setCodeBusy(true);
    try {
      const next = rotate ? await api.accessCode.rotate() : await api.accessCode.get();
      setAccessCode(next);
      void refresh();
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "Could not load the access code.");
    } finally {
      setCodeBusy(false);
    }
  };

  // Mint / refresh the code whenever Anywhere + tunnel is live.
  useEffect(() => {
    if (!open || mode !== "tunnel" || !tunnelLive || missingBinary) return;
    void loadAccessCode(false);
    const timer = window.setInterval(() => {
      void loadAccessCode(false);
    }, 5_000);
    return () => window.clearInterval(timer);
  }, [open, mode, tunnelLive, missingBinary, gateEnabled]);

  // Prefer digits from live /state when present (keeps countdown in sync).
  const displayCode =
    accessCode?.display ||
    state?.gate?.display ||
    (state?.gate?.code ? `${state.gate.code.slice(0, 3)} ${state.gate.code.slice(3)}` : null);
  const rawCode = accessCode?.code || state?.gate?.code || null;
  const expiresIn =
    accessCode?.expires_in_sec ?? state?.gate?.code_expires_in_sec ?? null;

  const currentUrl = window.location.origin;
  const lanUrl = useMemo(() => localTarget(info, currentUrl), [info, currentUrl]);
  const tunnelUrl = tunnel?.url ?? info?.tunnel_url ?? null;
  const target = mode === "tunnel" && tunnelUrl ? tunnelUrl : lanUrl;
  const viaTunnel = mode === "tunnel" && Boolean(tunnelUrl);

  const otherAddresses = useMemo(() => {
    if (!info) return [] as string[];
    return [info.local_url, ...info.lan_urls, tunnelUrl]
      .filter((url): url is string => Boolean(url))
      .filter((url, index, all) => url !== target && all.indexOf(url) === index);
  }, [info, target, tunnelUrl]);

  const setTunnel = async (enabled: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await api.tunnel.set(enabled);
      if (enabled) setMode("tunnel");
      else {
        setMode("local");
        setAccessCode(null);
      }
      await refresh(true);
      const next = await api.network();
      setInfo(next);
      if (enabled) await loadAccessCode(false);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "Could not update the tunnel.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="icon" title="Open on your phone">
          <Smartphone />
          <span className="sr-only">Open on your phone</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Open on your phone</DialogTitle>
          <DialogDescription>
            Same Wi-Fi needs no setup. For anywhere else, turn on the Cloudflare tunnel —
            when someone opens the link, you can tap Allow here, or share the 6-digit code.
          </DialogDescription>
        </DialogHeader>

        <div className="bg-secondary/70 flex gap-1 rounded-2xl p-1">
          <button
            type="button"
            className={cn(
              "flex flex-1 items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-sm font-medium transition-[background-color,color,transform] duration-300",
              mode === "local" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground",
            )}
            onClick={() => setMode("local")}
          >
            <Wifi className="size-3.5" />
            This Wi-Fi
          </button>
          <button
            type="button"
            className={cn(
              "flex flex-1 items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-sm font-medium transition-[background-color,color,transform] duration-300",
              mode === "tunnel" ? "bg-card text-foreground shadow-sm" : "text-muted-foreground",
            )}
            onClick={() => setMode("tunnel")}
          >
            <Globe className="size-3.5" />
            Anywhere
          </button>
        </div>

        {mode === "tunnel" ? (
          <div className="border-hairline flex items-center justify-between gap-3 rounded-2xl border px-3 py-2.5">
            <div className="min-w-0">
              <p className="text-sm font-medium">Cloudflare tunnel</p>
              <p className="text-muted-foreground text-xs">
                {missingBinary
                  ? "cloudflared is not installed on this machine."
                  : tunnelLive
                    ? "Live public HTTPS link"
                    : tunnelStarting
                      ? "Starting… minting a trycloudflare.com URL"
                      : "Off — turn on to share outside this Wi-Fi"}
              </p>
            </div>
            <Switch
              checked={Boolean(tunnel?.desired || tunnel?.running || tunnelLive)}
              disabled={busy || missingBinary}
              onCheckedChange={(value) => void setTunnel(value)}
              aria-label="Cloudflare tunnel"
            />
          </div>
        ) : null}

        {mode === "tunnel" && missingBinary ? (
          <Alert variant="warning">
            <AlertTitle>Install cloudflared</AlertTitle>
            <AlertDescription>
              <p>
                Homebrew: <code>brew install cloudflared</code>
              </p>
            </AlertDescription>
          </Alert>
        ) : null}

        <div className="flex flex-col items-center gap-3">
          {mode === "tunnel" && !tunnelUrl ? (
            <div className="bg-secondary text-muted-foreground flex aspect-square w-full max-w-[220px] flex-col items-center justify-center gap-2 rounded-2xl text-sm text-center">
              {tunnelStarting || busy ? (
                <>
                  <Loader2 className="size-6 animate-spin" />
                  Waiting for public URL…
                </>
              ) : (
                <>
                  <Globe className="size-6" />
                  Turn the tunnel on to get a QR code
                </>
              )}
            </div>
          ) : (
            <QrCode value={target} alt={`QR code for ${target}`} />
          )}

          {target && (mode === "local" || tunnelUrl) ? (
            <>
              <code className="bg-secondary w-full rounded-xl px-3 py-2 text-center text-sm break-all">
                {target}
              </code>
              <div className="text-muted-foreground flex items-center gap-1.5 text-xs">
                {viaTunnel ? <Globe className="size-3.5" /> : <Wifi className="size-3.5" />}
                {viaTunnel ? "Public tunnel (HTTPS)" : "Local network"}
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={async () => {
                  const ok = await copyText(target);
                  setCopied(ok ? "url" : null);
                  window.setTimeout(() => setCopied(null), 2000);
                }}
              >
                {copied === "url" ? <Check /> : <Copy />}
                {copied === "url" ? "Copied" : "Copy address"}
              </Button>
            </>
          ) : null}
        </div>

        {viaTunnel && gateEnabled ? (
          <div className="border-hairline space-y-3 rounded-2xl border px-4 py-4 text-center">
            <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
              Access code
            </p>
            {displayCode ? (
              <p
                className="font-mono text-4xl font-semibold tracking-[0.28em] tabular-nums"
                aria-label={`Access code ${displayCode}`}
              >
                {displayCode}
              </p>
            ) : (
              <div className="text-muted-foreground flex items-center justify-center gap-2 py-3 text-sm">
                <Loader2 className="size-4 animate-spin" />
                Preparing code…
              </div>
            )}
            <p className="text-muted-foreground text-xs">
              Optional fallback — prefer Allow when their request appears.{" "}
              {expiresIn != null ? formatExpiry(expiresIn) : "It expires in a few minutes."}
            </p>
            <div className="flex flex-wrap justify-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                disabled={!rawCode}
                onClick={async () => {
                  if (!rawCode) return;
                  const ok = await copyText(rawCode);
                  setCopied(ok ? "code" : null);
                  window.setTimeout(() => setCopied(null), 2000);
                }}
              >
                {copied === "code" ? <Check /> : <Copy />}
                {copied === "code" ? "Copied" : "Copy code"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={codeBusy}
                onClick={() => void loadAccessCode(true)}
              >
                {codeBusy ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                New code
              </Button>
            </div>
          </div>
        ) : null}

        {viaTunnel && !gateEnabled ? (
          <Alert variant="warning">
            <AlertTitle>Access gate is off</AlertTitle>
            <AlertDescription>
              Anyone with the link can control toys. Set <code>LOVENSE_GATE=1</code> (default)
              to require a code again.
            </AlertDescription>
          </Alert>
        ) : null}

        {tunnel?.last_error ? (
          <Alert variant="warning">
            <AlertDescription>{tunnel.last_error}</AlertDescription>
          </Alert>
        ) : null}

        {otherAddresses.length > 0 ? (
          <div className="text-muted-foreground space-y-1.5 text-xs">
            <p className="font-medium text-foreground/80">Other addresses</p>
            {otherAddresses.map((url) => (
              <button
                key={url}
                type="button"
                className="hover:text-foreground block w-full rounded-lg text-left break-all transition-colors duration-300"
                onClick={() => {
                  if (url.includes("trycloudflare.com")) setMode("tunnel");
                  else setMode("local");
                }}
              >
                <code>{url}</code>
              </button>
            ))}
          </div>
        ) : null}

        {error ? (
          <Alert variant="warning">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
