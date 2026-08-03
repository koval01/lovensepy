import type { TaskRow } from "@/lib/types";

/** Human labels for Lovense action names. */
const FEATURE_LABELS: Record<string, string> = {
  Vibrate: "Vibration",
  Vibrate1: "Vibration 1",
  Vibrate2: "Vibration 2",
  Vibrate3: "Vibration 3",
  Rotate: "Rotation",
  Pump: "Air pump",
  Thrusting: "Thrusting",
  Fingering: "Fingering",
  Suction: "Suction",
  Depth: "Depth",
  Stroke: "Stroke",
  Oscillate: "Oscillation",
  All: "All motors",
};

export function featureLabel(feature: string) {
  return FEATURE_LABELS[feature] ?? feature;
}

export function presetLabel(preset: string) {
  return preset.charAt(0).toUpperCase() + preset.slice(1);
}

export function toyTypeLabel(toyType: string | null | undefined) {
  if (!toyType) return null;
  return toyType.charAt(0).toUpperCase() + toyType.slice(1);
}

export function formatSeconds(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined) return "∞";
  const total = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes === 0) return `${rest}s`;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

export function formatDuration(seconds: number) {
  if (seconds <= 0) return "Until stopped";
  if (seconds < 60) return `${seconds}s`;
  const minutes = seconds / 60;
  return Number.isInteger(minutes) ? `${minutes} min` : `${minutes.toFixed(1)} min`;
}

/** RSSI → 0..4 bars. -50 dBm and better is "next to the radio". */
export function signalBars(rssi: number | null | undefined) {
  if (rssi === null || rssi === undefined) return 0;
  if (rssi >= -55) return 4;
  if (rssi >= -67) return 3;
  if (rssi >= -78) return 2;
  if (rssi >= -90) return 1;
  return 0;
}

export function batteryTone(battery: number | null | undefined) {
  if (battery === null || battery === undefined) return "text-muted-foreground";
  if (battery <= 15) return "text-destructive";
  if (battery <= 35) return "text-muted-foreground";
  return "text-foreground";
}

export function taskTitle(task: TaskRow) {
  switch (task.kind) {
    case "function":
      return `${featureLabel(task.feature ?? "")} · level ${Math.round(task.level ?? 0)}`;
    case "function_loop": {
      const actions = Object.entries(task.actions ?? {})
        .map(([feature, level]) => `${featureLabel(feature)} ${Math.round(level)}`)
        .join(", ");
      return `Pulse loop · ${actions || "motors"}`;
    }
    case "preset":
      return `Preset · ${presetLabel(task.preset ?? "")}`;
    case "pattern":
      return task.template
        ? `Pattern · ${presetLabel(task.template)}`
        : `Pattern · ${task.pattern_length ?? 0} steps`;
    default:
      return task.kind;
  }
}

export function taskSubtitle(task: TaskRow) {
  const parts: string[] = [];
  if (task.kind === "function_loop") {
    if (task.loop_on_time) parts.push(`${task.loop_on_time}s on`);
    if (task.loop_off_time) parts.push(`${task.loop_off_time}s off`);
  }
  if (task.kind === "pattern" && task.interval) parts.push(`${task.interval}ms step`);
  if (task.extension_count) parts.push(`extended ${task.extension_count}×`);
  return parts.join(" · ");
}

const relative = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

export function relativeSeconds(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined) return "";
  if (seconds < 60) return relative.format(-Math.round(seconds), "second");
  if (seconds < 3600) return relative.format(-Math.round(seconds / 60), "minute");
  return relative.format(-Math.round(seconds / 3600), "hour");
}
