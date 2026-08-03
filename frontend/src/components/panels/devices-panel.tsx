import { Bluetooth, Compass, Info, TriangleAlert } from "lucide-react";

import { AutoConnectButton } from "@/components/auto-connect-button";
import { DeviceCard } from "@/components/device-card";
import { RemotePresenceCard } from "@/components/remote-presence-card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useService } from "@/hooks/use-service";

function DeviceSkeleton() {
  return (
    <Card className="gap-3">
      <CardContent className="space-y-4">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-3 w-48" />
        <Skeleton className="h-7 w-full" />
        <Skeleton className="h-7 w-full" />
        <Skeleton className="h-9 w-40" />
      </CardContent>
    </Card>
  );
}

export function DevicesPanel({ onOpenDiscover }: { onOpenDiscover: () => void }) {
  const { state, role } = useService();
  const isHost = role !== "remote";

  if (!state) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <DeviceSkeleton />
        <DeviceSkeleton />
      </div>
    );
  }

  const noTransport = !state.transports.lan && !state.transports.ble && !state.transports.socket;

  if (noTransport) {
    return (
      <Alert variant="info">
        <Info />
        <AlertTitle>No connection method is enabled</AlertTitle>
        <AlertDescription>
          <p>
            {isHost
              ? "Pick how this machine should reach your toys — Bluetooth, the Lovense app on your LAN, or the Lovense cloud."
              : "The host has not enabled a connection method yet. Ask them to finish setup on the local machine."}
          </p>
          {isHost ? (
            <Button className="mt-2 w-fit" onClick={onOpenDiscover}>
              <Compass /> Open setup
            </Button>
          ) : null}
        </AlertDescription>
      </Alert>
    );
  }

  if (state.toys.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-8 text-center">
          <Bluetooth className="text-muted-foreground size-8" />
          <div>
            <p className="font-medium">No devices yet</p>
            <p className="text-muted-foreground text-sm">
              {isHost
                ? state.transports.ble
                  ? "Turn a toy on and hold it near this machine, then scan."
                  : "Pair a toy in the Lovense app, then refresh."
                : "Waiting for the host to connect a toy."}
            </p>
          </div>
          {isHost ? (
            <div className="flex flex-wrap justify-center gap-2">
              {state.transports.ble ? <AutoConnectButton /> : null}
              <Button variant="outline" onClick={onOpenDiscover}>
                <Compass /> Connection options
              </Button>
            </div>
          ) : null}
          {state.toys_error ? (
            <p className="text-muted-foreground max-w-sm text-xs">{state.toys_error}</p>
          ) : null}
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <RemotePresenceCard compact />

      {state.toys_error ? (
        <Alert variant="warning">
          <TriangleAlert />
          <AlertTitle>Some devices could not be read</AlertTitle>
          <AlertDescription>{state.toys_error}</AlertDescription>
        </Alert>
      ) : null}

      <div className="grid auto-rows-fr items-stretch gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {state.toys.map((toy) => (
          <DeviceCard key={toy.id} toy={toy} />
        ))}
      </div>

      {isHost && state.transports.ble ? (
        <div className="flex justify-center pt-1">
          <AutoConnectButton variant="outline" size="sm" label="Scan for more" />
        </div>
      ) : null}
    </div>
  );
}
