import { Cloud, ExternalLink, Loader2, QrCode as QrIcon, RefreshCw } from "lucide-react";
import { useState } from "react";

import { QrCode } from "@/components/qr-code";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAsyncAction } from "@/hooks/use-async-action";
import { useService } from "@/hooks/use-service";
import { api } from "@/lib/api";

/** Lovense hands out either a QR image URL or a payload string; handle both. */
function looksLikeImage(value: string) {
  return /^https?:\/\//i.test(value) && /\.(png|jpe?g|gif|webp|svg)(\?|$)/i.test(value);
}

function CredentialsForm() {
  const { refresh } = useService();
  const [developerToken, setDeveloperToken] = useState("");
  const [uid, setUid] = useState("");
  const [platform, setPlatform] = useState("lovensepy");

  const [save, saving] = useAsyncAction(
    () =>
      api.config.setSocket({
        developer_token: developerToken.trim(),
        uid: uid.trim(),
        platform: platform.trim(),
      }),
    {
      success: "Lovense cloud enabled",
      errorTitle: "Could not enable the Lovense cloud",
      onDone: () => void refresh(true),
    },
  );

  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <div className="space-y-1.5">
        <Label htmlFor="socket-token">Developer token</Label>
        <Input
          id="socket-token"
          value={developerToken}
          onChange={(event) => setDeveloperToken(event.target.value)}
          autoComplete="off"
          spellCheck={false}
          placeholder="From the Lovense developer dashboard"
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="socket-uid">User id</Label>
          <Input
            id="socket-uid"
            value={uid}
            onChange={(event) => setUid(event.target.value)}
            autoComplete="off"
            spellCheck={false}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="socket-platform">Platform name</Label>
          <Input
            id="socket-platform"
            value={platform}
            onChange={(event) => setPlatform(event.target.value)}
            autoComplete="off"
            spellCheck={false}
          />
        </div>
      </div>
      <Button type="submit" disabled={saving || !developerToken.trim() || !uid.trim()}>
        {saving ? <Loader2 className="animate-spin" /> : <Cloud />} Enable
      </Button>
      <p className="text-muted-foreground text-xs">
        Stored in memory for this run only — nothing is written to disk.
      </p>
    </form>
  );
}

export function SocketPairingCard() {
  const { state, refresh } = useService();
  const socket = state?.socket;
  const enabled = state?.transports.socket ?? false;
  const configured = state?.config.socket.has_developer_token && state?.config.socket.has_uid;

  const [request, requesting] = useAsyncAction(() => api.socket.requestQr(), {
    errorTitle: "Could not ask for a new code",
    onDone: () => void refresh(),
  });

  const raw = socket?.qr.qrcodeUrl || socket?.qr.qrcode || null;
  const connected = Boolean(socket?.status.socket_io_connected);
  const appOnline = socket?.status.app_online;
  const pairedToys = socket?.status.toy_ids?.length ?? 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Cloud className="size-4" /> Lovense app (cloud)
          {enabled ? (
            <Badge variant={connected ? "success" : "warning"} className="ml-auto">
              {connected ? "Connected" : "Connecting"}
            </Badge>
          ) : null}
        </CardTitle>
        <CardDescription>
          Pair by scanning a code in the Lovense Remote app. Works over the internet, so
          the phone does not have to be on this Wi-Fi.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!enabled || !configured ? (
          <CredentialsForm />
        ) : (
          <>
            <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
              <span>App {appOnline ? "online" : appOnline === false ? "offline" : "unknown"}</span>
              <span>
                {pairedToys} paired toy{pairedToys === 1 ? "" : "s"}
              </span>
              {state?.config.socket.use_local_commands ? <span>Local commands on</span> : null}
            </div>

            {raw ? (
              <div className="flex flex-col items-center gap-3">
                {looksLikeImage(raw) ? (
                  <img
                    src={raw}
                    alt="Lovense pairing QR code"
                    className="size-52 rounded-xl bg-white p-2 shadow-sm"
                  />
                ) : (
                  <QrCode value={raw} alt="Lovense pairing QR code" />
                )}
                <div className="flex flex-wrap justify-center gap-2">
                  <Button variant="outline" size="sm" disabled={requesting} onClick={() => void request()}>
                    {requesting ? <Loader2 className="animate-spin" /> : <RefreshCw />} New code
                  </Button>
                  {/^https?:\/\//i.test(raw) ? (
                    <Button variant="ghost" size="sm" asChild>
                      <a href={raw} target="_blank" rel="noreferrer noopener">
                        <ExternalLink /> Open link
                      </a>
                    </Button>
                  ) : null}
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-3 py-2 text-center">
                <QrIcon className="text-muted-foreground size-8" />
                <p className="text-muted-foreground text-sm">
                  Waiting for a pairing code from Lovense.
                </p>
                <Button variant="outline" size="sm" disabled={requesting} onClick={() => void request()}>
                  {requesting ? <Loader2 className="animate-spin" /> : <RefreshCw />} Request code
                </Button>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
