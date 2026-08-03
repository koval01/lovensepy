import { Loader2, Router, Wifi } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAsyncAction } from "@/hooks/use-async-action";
import { useService } from "@/hooks/use-service";
import { api } from "@/lib/api";

/** Game Mode in the Lovense app: it prints the host and port to point at. */
export function LanSetupCard() {
  const { state, refresh } = useService();
  const lan = state?.config.lan;
  const [host, setHost] = useState("");
  const [port, setPort] = useState("");

  // Prefill from the service once, then leave the fields alone while editing.
  useEffect(() => {
    if (lan?.ip) setHost((current) => current || lan.ip!);
    if (lan?.port) setPort((current) => current || String(lan.port));
  }, [lan?.ip, lan?.port]);

  const [save, saving] = useAsyncAction(
    () => api.config.setLanIp(host.trim(), port ? Number(port) : undefined),
    {
      success: "Lovense app connected",
      errorTitle: "Could not reach the Lovense app",
      onDone: () => void refresh(true),
    },
  );

  const active = Boolean(lan?.enabled && lan?.ip);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Wifi className="size-4" /> Lovense app on this network
          {active ? (
            <Badge variant="success" className="ml-auto">
              {lan?.ip}:{lan?.port}
            </Badge>
          ) : null}
        </CardTitle>
        <CardDescription>
          Enable <span className="font-medium">Game Mode</span> in Lovense Remote; it shows a
          local address. Everything the app can reach becomes controllable here.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <div className="min-w-[10rem] flex-1 space-y-1.5">
            <Label htmlFor="lan-host">Address</Label>
            <Input
              id="lan-host"
              value={host}
              onChange={(event) => setHost(event.target.value)}
              placeholder="192.168.1.42"
              inputMode="decimal"
              autoComplete="off"
              spellCheck={false}
            />
          </div>
          <div className="w-24 space-y-1.5">
            <Label htmlFor="lan-port">Port</Label>
            <Input
              id="lan-port"
              value={port}
              onChange={(event) => setPort(event.target.value.replace(/\D/g, ""))}
              placeholder="20010"
              inputMode="numeric"
              autoComplete="off"
            />
          </div>
          <Button type="submit" disabled={saving || host.trim().length < 7}>
            {saving ? <Loader2 className="animate-spin" /> : <Router />} Connect
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
