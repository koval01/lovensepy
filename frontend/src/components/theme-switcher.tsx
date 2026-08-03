import { Monitor, Moon, Sun } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useTheme, type Theme } from "@/hooks/use-theme";
import { cn } from "@/lib/utils";

const ORDER: Theme[] = ["system", "light", "dark"];

function iconFor(theme: Theme) {
  if (theme === "light") return Sun;
  if (theme === "dark") return Moon;
  return Monitor;
}

function labelFor(theme: Theme, resolved: "light" | "dark") {
  if (theme === "system") return `Auto · ${resolved}`;
  return theme === "light" ? "Light" : "Dark";
}

/** Compact header control: cycles Auto → Light → Dark and follows the OS in Auto. */
export function ThemeSwitcher({ className }: { className?: string }) {
  const { theme, setTheme, resolved } = useTheme();
  const Icon = iconFor(theme);
  const label = labelFor(theme, resolved);

  return (
    <Button
      variant="outline"
      size="icon"
      className={cn(className)}
      title={`Theme: ${label}. Tap to switch.`}
      aria-label={`Theme: ${label}. Tap to switch.`}
      onClick={() => {
        const index = ORDER.indexOf(theme);
        setTheme(ORDER[(index + 1) % ORDER.length] ?? "system");
      }}
    >
      <Icon />
      <span className="sr-only">{label}</span>
    </Button>
  );
}

/** Full three-way control used in Settings. */
export function ThemeToggleGroup({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme();
  return (
    <ToggleGroup
      type="single"
      value={theme}
      onValueChange={(value) => value && setTheme(value as Theme)}
      aria-label="Theme"
      className={className}
    >
      <ToggleGroupItem value="system" title="Match the system">
        <Monitor />
        <span className="sr-only">Auto</span>
      </ToggleGroupItem>
      <ToggleGroupItem value="light" title="Light">
        <Sun />
        <span className="sr-only">Light</span>
      </ToggleGroupItem>
      <ToggleGroupItem value="dark" title="Dark">
        <Moon />
        <span className="sr-only">Dark</span>
      </ToggleGroupItem>
    </ToggleGroup>
  );
}
