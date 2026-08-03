import { BleDiscoveryCard } from "@/components/ble-discovery-card";
import { LanSetupCard } from "@/components/lan-setup-card";
import { SocketPairingCard } from "@/components/socket-pairing-card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useAsyncAction } from "@/hooks/use-async-action";
import { useService } from "@/hooks/use-service";
import { api } from "@/lib/api";
import { Bluetooth, Info } from "lucide-react";

export function DiscoverPanel() {
  const { state, refresh } = useService();
  const bleOff = state !== null && !state.transports.ble;

  const [enableBle] = useAsyncAction(() => api.config.setTransports({ ble: true }), {
    success: "Bluetooth enabled",
    errorTitle: "Could not enable Bluetooth",
    onDone: () => void refresh(true),
  });

  return (
    <div className="space-y-4">
      {bleOff ? (
        <Alert variant="info">
          <Info />
          <AlertTitle>Bluetooth is off</AlertTitle>
          <AlertDescription>
            <p>Turn it on to connect toys directly, without the Lovense app.</p>
            <Button size="sm" className="mt-2 w-fit" onClick={() => void enableBle()}>
              <Bluetooth /> Enable Bluetooth
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      <BleDiscoveryCard />
      <LanSetupCard />
      <SocketPairingCard />
    </div>
  );
}
