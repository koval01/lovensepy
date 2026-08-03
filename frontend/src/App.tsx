import { Activity, Compass, Gauge, Loader2, Settings, Square, WifiOff } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { LinkBadge } from "@/components/link-badge";
import { DevicesPanel } from "@/components/panels/devices-panel";
import { DiscoverPanel } from "@/components/panels/discover-panel";
import { SessionsPanel } from "@/components/panels/sessions-panel";
import { SettingsPanel } from "@/components/panels/settings-panel";
import { AccessApprovalToasts } from "@/components/access-approval-toasts";
import { PhoneAccessDialog } from "@/components/phone-access-dialog";
import { ThemeSwitcher } from "@/components/theme-switcher";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAsyncAction } from "@/hooks/use-async-action";
import { useLocalSetting } from "@/hooks/use-local-setting";
import { useService } from "@/hooks/use-service";
import { useWakeLock } from "@/hooks/use-wake-lock";
import { api } from "@/lib/api";

const ALL_TABS = [
  { value: "devices", label: "Devices", icon: Gauge, hostOnly: false },
  { value: "sessions", label: "Running", icon: Activity, hostOnly: false },
  { value: "discover", label: "Connect", icon: Compass, hostOnly: true },
  { value: "settings", label: "Settings", icon: Settings, hostOnly: true },
] as const;

function BrandMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden
      className={className}
      fill="currentColor"
    >
      <path d="M12 3.2c-2.1 0-3.8 1.7-3.8 3.8 0 3.4 3.8 7.2 3.8 7.2s3.8-3.8 3.8-7.2c0-2.1-1.7-3.8-3.8-3.8Zm0 5.4a1.6 1.6 0 1 1 0-3.2 1.6 1.6 0 0 1 0 3.2ZM6.4 18.2c0-2.4 2.5-4.4 5.6-4.4s5.6 2 5.6 4.4v.6H6.4v-.6Z" />
    </svg>
  );
}

export default function App() {
  const { state, status, error, refresh, reportPresence, role } = useService();
  const [tab, setTab] = useState<string>("devices");
  const activeCount = state?.tasks.length ?? 0;
  const remoteCount = state?.presence?.remotes?.length ?? 0;
  const isHost = role !== "remote";
  const isRemote = role === "remote";

  const tabs = useMemo(
    () => ALL_TABS.filter((item) => isHost || !item.hostOnly),
    [isHost],
  );

  const [keepAwake] = useLocalSetting("keep-awake", true);
  useWakeLock(keepAwake && activeCount > 0);

  // Tunnel visitors never see Connect / Settings — bounce them back to Devices.
  useEffect(() => {
    if (isRemote && (tab === "discover" || tab === "settings")) {
      setTab("devices");
    }
  }, [isRemote, tab]);

  useEffect(() => {
    reportPresence({ tab, activity: `Viewing ${tab}` });
  }, [tab, reportPresence]);

  const [stopAll, stopping] = useAsyncAction(() => api.command.stopAll(), {
    errorTitle: "Stop failed",
    onDone: () => void refresh(),
  });

  return (
    <div className="bg-background text-foreground select-none min-h-[100dvh]">
      {isHost ? <AccessApprovalToasts /> : null}
      <header className="glass-chrome safe-top sticky top-0 z-40 border-b border-hairline">
        <div className="safe-x mx-auto flex h-14 max-w-6xl items-center gap-2.5">
          <BrandMark className="size-5 shrink-0" />
          <span className="text-[0.95rem] font-semibold tracking-tight">LovensePy</span>
          <div className="ml-0.5 hidden items-center gap-1.5 sm:flex">
            <LinkBadge status={status} />
            {isHost && remoteCount > 0 ? (
              <Badge variant="outline" title="Remote controllers online">
                {remoteCount} remote
              </Badge>
            ) : null}
            {isRemote ? (
              <Badge variant="outline" title="Control-only access over the public tunnel">
                Remote
              </Badge>
            ) : null}
          </div>

          <div className="ml-auto flex items-center gap-2">
            <div className="sm:hidden">
              <LinkBadge status={status} />
            </div>
            <ThemeSwitcher />
            {isHost ? <PhoneAccessDialog /> : null}
            <Button
              variant={activeCount > 0 ? "destructive" : "outline"}
              disabled={stopping || activeCount === 0}
              onClick={() => void stopAll()}
            >
              {stopping ? <Loader2 className="animate-spin" /> : <Square />}
              <span className="hidden sm:inline">Stop all</span>
            </Button>
          </div>
        </div>
      </header>

      <Tabs value={tab} onValueChange={setTab} className="w-full">
        <main className="safe-x mx-auto w-full max-w-6xl space-y-4 py-5 pb-28 sm:pb-10">
          <TabsList className="hidden sm:inline-flex sm:w-auto">
            {tabs.map(({ value, label, icon: Icon }) => (
              <TabsTrigger key={value} value={value} className="flex-none px-4">
                <Icon />
                {label}
                {value === "sessions" && activeCount > 0 ? (
                  <Badge variant="default" className="ml-1 px-1.5">
                    {activeCount}
                  </Badge>
                ) : null}
              </TabsTrigger>
            ))}
          </TabsList>

          {status === "offline" ? (
            <Alert variant="destructive" className="motion-safe-fade">
              <WifiOff />
              <AlertTitle>Lost contact with the service</AlertTitle>
              <AlertDescription>
                {error ?? "Retrying automatically."} Toys keep whatever they were last told
                to do until the connection is back.
              </AlertDescription>
            </Alert>
          ) : null}

          {isRemote ? (
            <Alert variant="info" className="motion-safe-fade">
              <AlertTitle>Remote control</AlertTitle>
              <AlertDescription>
                You can adjust intensity, run presets and patterns, and see battery and
                running sessions. Settings, pairing, and the Cloudflare tunnel are only
                available on the host machine.
              </AlertDescription>
            </Alert>
          ) : null}

          <TabsContent value="devices" className="motion-safe-rise">
            <DevicesPanel onOpenDiscover={() => setTab("discover")} />
          </TabsContent>
          <TabsContent value="sessions" className="motion-safe-rise">
            <SessionsPanel />
          </TabsContent>
          {isHost ? (
            <>
              <TabsContent value="discover" className="motion-safe-rise">
                <DiscoverPanel />
              </TabsContent>
              <TabsContent value="settings" className="motion-safe-rise">
                <SettingsPanel />
              </TabsContent>
            </>
          ) : null}
        </main>

        {/* Bottom navigation on phones: within thumb reach and out of the way of sliders. */}
        <TabsList className="glass-chrome safe-bottom fixed inset-x-0 bottom-0 z-40 h-auto justify-around rounded-none border-t border-hairline p-1.5 sm:hidden">
          {tabs.map(({ value, label, icon: Icon }) => (
            <TabsTrigger
              key={value}
              value={value}
              className="h-12 flex-col gap-0.5 rounded-xl text-[0.68rem] data-[state=active]:bg-foreground/8 data-[state=active]:shadow-none"
            >
              <span className="relative">
                <Icon />
                {value === "sessions" && activeCount > 0 ? (
                  <span className="bg-foreground text-background absolute -top-1 -right-2 grid size-4 place-items-center rounded-full text-[0.6rem] font-semibold">
                    {activeCount}
                  </span>
                ) : null}
              </span>
              {label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
    </div>
  );
}
