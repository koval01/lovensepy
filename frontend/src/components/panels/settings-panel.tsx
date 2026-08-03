import { BookOpen, Bluetooth, Cloud, Globe, Loader2, Wifi } from "lucide-react";
import { useState, type ReactNode } from "react";

import { RemotePresenceCard } from "@/components/remote-presence-card";
import { ThemeToggleGroup } from "@/components/theme-switcher";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useAsyncAction } from "@/hooks/use-async-action";
import { useLocalSetting } from "@/hooks/use-local-setting";
import { useService } from "@/hooks/use-service";
import { useTheme } from "@/hooks/use-theme";
import { wakeLockSupported } from "@/hooks/use-wake-lock";
import { api } from "@/lib/api";
import { formatSeconds } from "@/lib/format";

function SettingRow({
  label,
  description,
  children,
}: {
  label: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 py-3">
      <div className="min-w-0">
        <p className="text-sm font-medium">{label}</p>
        {description ? <p className="text-muted-foreground text-xs">{description}</p> : null}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function TransportsCard() {
  const { state, refresh } = useService();
  const [pendingKey, setPendingKey] = useState<string | null>(null);

  const toggle = async (key: "lan" | "ble" | "socket", value: boolean) => {
    setPendingKey(key);
    try {
      await api.config.setTransports({ [key]: value });
    } finally {
      setPendingKey(null);
      void refresh(true);
    }
  };

  const rows: Array<{
    key: "lan" | "ble" | "socket";
    label: string;
    description: string;
    icon: ReactNode;
  }> = [
    {
      key: "ble",
      label: "Bluetooth",
      description: "Talk to toys directly from this machine.",
      icon: <Bluetooth className="size-4" />,
    },
    {
      key: "lan",
      label: "Lovense app (LAN)",
      description: "Use Game Mode on a device on this network.",
      icon: <Wifi className="size-4" />,
    },
    {
      key: "socket",
      label: "Lovense cloud",
      description: "Pair through the Lovense servers with a QR code.",
      icon: <Cloud className="size-4" />,
    },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Connection methods</CardTitle>
        <CardDescription>
          Several can run at once; commands are routed to whichever owns the device.
        </CardDescription>
      </CardHeader>
      <CardContent className="divide-border divide-y">
        {rows.map((row) => (
          <SettingRow key={row.key} label={row.label} description={row.description}>
            <div className="flex items-center gap-2">
              {pendingKey === row.key ? (
                <Loader2 className="text-muted-foreground size-4 animate-spin" />
              ) : (
                <span className="text-muted-foreground">{row.icon}</span>
              )}
              <Switch
                checked={state?.transports[row.key] ?? false}
                disabled={!state || pendingKey !== null}
                onCheckedChange={(value) => void toggle(row.key, value)}
                aria-label={row.label}
              />
            </div>
          </SettingRow>
        ))}
      </CardContent>
    </Card>
  );
}

function BleOptionsCard() {
  const { state, refresh } = useService();
  const ble = state?.config.ble;
  const [prefix, setPrefix] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  if (!state?.transports.ble || !ble) return null;

  const apply = async (body: Parameters<typeof api.config.setBle>[0]) => {
    setSaving(true);
    try {
      await api.config.setBle(body);
    } finally {
      setSaving(false);
      void refresh(true);
    }
  };

  const prefixValue = prefix ?? ble.scan_name_prefix ?? "";

  return (
    <Card>
      <CardHeader>
        <CardTitle>Bluetooth behaviour</CardTitle>
        <CardDescription>
          Defaults are tuned for "just works"; change them only if a device misbehaves.
        </CardDescription>
      </CardHeader>
      <CardContent className="divide-border divide-y">
        <SettingRow
          label="Keep devices connected"
          description={`Reconnects dropped toys every ${formatSeconds(ble.auto_reconnect_interval_sec)}.`}
        >
          <Switch
            checked={ble.auto_reconnect}
            disabled={saving}
            onCheckedChange={(value) => void apply({ auto_reconnect: value })}
            aria-label="Keep devices connected"
          />
        </SettingRow>

        <SettingRow
          label="Keep scanning in the background"
          description="Refreshes signal strength and finds toys as they wake up."
        >
          <Switch
            checked={ble.advertisement_monitor}
            disabled={saving}
            onCheckedChange={(value) => void apply({ advertisement_monitor: value })}
            aria-label="Keep scanning in the background"
          />
        </SettingRow>

        <SettingRow
          label="Emulate presets"
          description="Workaround for firmware that ignores built-in preset commands."
        >
          <Switch
            checked={ble.preset_emulate_pattern}
            disabled={saving}
            onCheckedChange={(value) => void apply({ preset_emulate_pattern: value })}
            aria-label="Emulate presets"
          />
        </SettingRow>

        <SettingRow label="Preset command" description="Older firmware expects 'Pat' instead.">
          <ToggleGroup
            type="single"
            value={ble.preset_uart_keyword}
            onValueChange={(value) => value && void apply({ preset_uart_keyword: value })}
            aria-label="Preset command keyword"
          >
            <ToggleGroupItem value="Preset" disabled={saving}>
              Preset
            </ToggleGroupItem>
            <ToggleGroupItem value="Pat" disabled={saving}>
              Pat
            </ToggleGroupItem>
          </ToggleGroup>
        </SettingRow>

        <div className="space-y-2 py-3">
          <Label htmlFor="scan-prefix">Scan filter</Label>
          <div className="flex gap-2">
            <Input
              id="scan-prefix"
              value={prefixValue}
              placeholder="LVS-"
              autoComplete="off"
              spellCheck={false}
              onChange={(event) => setPrefix(event.target.value)}
            />
            <Button
              variant="outline"
              disabled={saving || prefix === null || prefix === (ble.scan_name_prefix ?? "")}
              onClick={() => void apply({ scan_name_prefix: prefixValue }).then(() => setPrefix(null))}
            >
              Save
            </Button>
          </div>
          <p className="text-muted-foreground text-xs">
            Advertised-name prefix. Empty scans every Bluetooth device nearby — useful for
            toys that do not advertise as <code>LVS-</code>.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

function TunnelCard() {
  const { state, refresh } = useService();
  const tunnel = state?.tunnel;
  const [busy, setBusy] = useState(false);

  const toggle = async (enabled: boolean) => {
    setBusy(true);
    try {
      await api.tunnel.set(enabled);
    } finally {
      setBusy(false);
      void refresh(true);
    }
  };

  const missingBinary = tunnel && !tunnel.available;
  const active = Boolean(tunnel?.desired || tunnel?.running || tunnel?.url);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Globe className="size-4" /> Phone from anywhere
        </CardTitle>
        <CardDescription>
          Same control as the phone button in the header. Starts a Cloudflare quick tunnel so
          a phone that is not on this Wi-Fi can open the panel. Requires{" "}
          <code>cloudflared</code> on this machine.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <SettingRow
          label="Public tunnel"
          description={
            missingBinary
              ? "cloudflared was not found on PATH."
              : tunnel?.url
                ? "Live — shown in the phone QR dialog."
                : tunnel?.desired
                  ? "Starting… waiting for a trycloudflare.com URL."
                  : "Off. Same-Wi-Fi access still works without this."
          }
        >
          <Switch
            checked={active}
            disabled={busy || missingBinary}
            onCheckedChange={(value) => void toggle(value)}
            aria-label="Public Cloudflare tunnel"
          />
        </SettingRow>

        {tunnel?.url ? (
          <code className="bg-secondary block rounded-md px-2 py-1.5 text-xs break-all">
            {tunnel.url}
          </code>
        ) : null}

        {tunnel?.last_error ? (
          <Alert variant="warning">
            <AlertDescription>{tunnel.last_error}</AlertDescription>
          </Alert>
        ) : null}

        {missingBinary ? (
          <Alert variant="warning">
            <AlertDescription>
              Install{" "}
              <a
                className="underline"
                href="https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
                target="_blank"
                rel="noreferrer"
              >
                cloudflared
              </a>{" "}
              (Homebrew: <code>brew install cloudflared</code>), or set{" "}
              <code>LOVENSE_CLOUDFLARED_BIN</code>, then retry. You can also start with{" "}
              <code>LOVENSE_TUNNEL=1 lovensepy-service</code>.
            </AlertDescription>
          </Alert>
        ) : (
          <Alert>
            <AlertDescription>
              The link is public while the tunnel is on. The first visitor is asked for a
              6-digit code that appears in this machine&apos;s console — turn the tunnel off
              when you are done sharing.
            </AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}

function AppearanceCard() {
  const { theme, resolved } = useTheme();
  const [keepAwake, setKeepAwake] = useLocalSetting("keep-awake", true);

  return (
    <Card>
      <CardHeader>
        <CardTitle>This browser</CardTitle>
        <CardDescription>
          Monochrome light and dark. Auto follows iOS / macOS appearance and updates live.
          Saved on this device only.
        </CardDescription>
      </CardHeader>
      <CardContent className="divide-border divide-y">
        <SettingRow
          label="Theme"
          description={
            theme === "system"
              ? `Auto · currently ${resolved}`
              : theme === "light"
                ? "Light"
                : "Dark"
          }
        >
          <ThemeToggleGroup />
        </SettingRow>

        {wakeLockSupported ? (
          <SettingRow
            label="Keep the screen awake"
            description="While something is running, so the stop button stays one tap away."
          >
            <Switch
              checked={keepAwake}
              onCheckedChange={setKeepAwake}
              aria-label="Keep the screen awake"
            />
          </SettingRow>
        ) : null}
      </CardContent>
    </Card>
  );
}

function AboutCard() {
  const { state } = useService();
  const [stopAll, stopping] = useAsyncAction(() => api.command.stopAll(), {
    success: "Everything stopped",
    errorTitle: "Stop failed",
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>About</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <dl className="text-sm">
          <div className="flex justify-between py-1">
            <dt className="text-muted-foreground">Version</dt>
            <dd className="font-mono">{state?.version ?? "—"}</dd>
          </div>
          <div className="flex justify-between py-1">
            <dt className="text-muted-foreground">Mode</dt>
            <dd className="font-mono">{state?.mode ?? "—"}</dd>
          </div>
          <div className="flex justify-between py-1">
            <dt className="text-muted-foreground">Running for</dt>
            <dd className="font-mono">{formatSeconds(state?.uptime_sec)}</dd>
          </div>
        </dl>

        <Separator />

        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" asChild>
            <a href="/docs" target="_blank" rel="noreferrer">
              <BookOpen /> API docs
            </a>
          </Button>
          <Button variant="outline" size="sm" asChild>
            <a href="/openapi.json" target="_blank" rel="noreferrer">
              OpenAPI
            </a>
          </Button>
          <Button
            variant="destructive"
            size="sm"
            className="ml-auto"
            disabled={stopping}
            onClick={() => void stopAll()}
          >
            {stopping ? <Loader2 className="animate-spin" /> : null} Stop everything
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function SettingsPanel() {
  return (
    <div className="space-y-4">
      <RemotePresenceCard />
      <TransportsCard />
      <BleOptionsCard />
      <TunnelCard />
      <AppearanceCard />
      <AboutCard />
    </div>
  );
}
