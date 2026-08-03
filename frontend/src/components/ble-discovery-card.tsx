import { Bluetooth, Check, Loader2, Plus, Radar, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";

import { AutoConnectButton } from "@/components/auto-connect-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAsyncAction } from "@/hooks/use-async-action";
import { useService } from "@/hooks/use-service";
import { api } from "@/lib/api";
import { signalBars } from "@/lib/format";
import type { ScanDevice } from "@/lib/types";

function DeviceRow({ device, registered }: { device: ScanDevice; registered: boolean }) {
  const { refresh } = useService();
  const [connect, connecting] = useAsyncAction(
    () => api.ble.connect({ address: device.address, name: device.name }),
    {
      success: `${device.name ?? device.address} connected`,
      errorTitle: "Could not connect",
      onDone: () => void refresh(true),
    },
  );

  return (
    <div className="flex items-center gap-3 py-2.5">
      <Bluetooth className="text-muted-foreground size-4 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{device.name ?? "Unnamed device"}</p>
        <p className="text-muted-foreground truncate font-mono text-xs">{device.address}</p>
      </div>
      {device.rssi !== null ? (
        <Badge variant="outline" className="shrink-0" title={`${device.rssi} dBm`}>
          {signalBars(device.rssi)}/4
        </Badge>
      ) : null}
      <Button
        size="sm"
        variant={registered ? "ghost" : "default"}
        disabled={connecting}
        onClick={() => void connect()}
      >
        {connecting ? <Loader2 className="animate-spin" /> : registered ? <RefreshCw /> : <Plus />}
        {registered ? "Reconnect" : "Add"}
      </Button>
    </div>
  );
}

export function BleDiscoveryCard() {
  const { state, refresh } = useService();
  const [scanned, setScanned] = useState<ScanDevice[] | null>(null);
  const enabled = state?.transports.ble ?? false;

  const registeredAddresses = useMemo(
    () =>
      new Set(
        (state?.ble?.registry ?? [])
          .map((row) => row.address?.toLowerCase())
          .filter((value): value is string => Boolean(value)),
      ),
    [state?.ble?.registry],
  );

  // Scan results win while they are fresh; otherwise show whatever the background
  // monitor has seen so the list is never empty for no reason.
  const rows: ScanDevice[] = useMemo(() => {
    if (scanned) return scanned;
    return (state?.ble?.advertisements ?? []).map((row) => ({
      address: row.address,
      name: row.name,
      rssi: row.rssi,
      suggested_toy_id: "",
      toy_type: null,
      registered: registeredAddresses.has(row.address.toLowerCase()),
    }));
  }, [registeredAddresses, scanned, state?.ble?.advertisements]);

  const [scan, scanning] = useAsyncAction(
    async () => {
      const result = await api.ble.scan(state?.ble?.scan.timeout_sec);
      setScanned(result.devices);
    },
    { errorTitle: "Scan failed", onDone: () => void refresh() },
  );

  if (!enabled) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Bluetooth className="size-4" /> Bluetooth
        </CardTitle>
        <CardDescription>
          Connects directly to the toy — no Lovense app, no account, no internet.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-2">
          <AutoConnectButton label="Connect everything" />
          <Button variant="outline" disabled={scanning} onClick={() => void scan()}>
            {scanning ? <Loader2 className="animate-spin" /> : <Radar />}
            {scanning ? "Scanning…" : "Scan only"}
          </Button>
        </div>

        {rows.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            Nothing nearby yet. Turn the toy on — its light should blink — and scan.
          </p>
        ) : (
          <div className="divide-border divide-y">
            {rows.map((device) => (
              <DeviceRow
                key={device.address}
                device={device}
                registered={
                  device.registered || registeredAddresses.has(device.address.toLowerCase())
                }
              />
            ))}
          </div>
        )}

        {state?.ble?.supervisor.enabled ? (
          <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
            <Check className="size-3.5" /> Devices you add stay connected automatically.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
