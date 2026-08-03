import type { ServiceState, TaskRow, ToyView } from "@/lib/types";
import { slotKey } from "@/lib/utils";

/**
 * Current level per (toy, motor) as the service sees it.
 *
 * `/tasks` is the source of truth: a `function` row is one motor being held, and a
 * `function_loop` row holds several motors at once. Anything not listed is at rest.
 */
export function levelsFromTasks(tasks: TaskRow[]): Map<string, number> {
  const levels = new Map<string, number>();
  for (const task of tasks) {
    if (!task.toy_id) continue;
    if (task.kind === "function" && task.feature) {
      levels.set(slotKey(task.toy_id, task.feature), Math.round(task.level ?? 0));
    } else if (task.kind === "function_loop" && task.actions) {
      for (const [feature, level] of Object.entries(task.actions)) {
        levels.set(slotKey(task.toy_id, feature), Math.round(level));
      }
    }
  }
  return levels;
}

export function tasksForToy(tasks: TaskRow[], toyId: string) {
  return tasks.filter((task) => task.toy_id === toyId);
}

/** Preset/pattern session running on a toy (or globally, when `toy_id` is null). */
export function modeSessionFor(tasks: TaskRow[], toyId: string) {
  return tasks.find(
    (task) =>
      (task.kind === "preset" || task.kind === "pattern") &&
      (task.toy_id === toyId || task.toy_id === null),
  );
}

export function isToyActive(tasks: TaskRow[], toyId: string) {
  return tasks.some((task) => task.toy_id === toyId || task.toy_id === null);
}

export function featureRange(state: ServiceState | null, feature: string): [number, number] {
  const range = state?.capabilities.function_ranges[feature];
  return range ? [range[0], range[1]] : [0, 20];
}

/** Motors we can actually drive on this toy, in a stable display order. */
export function controllableFeatures(toy: ToyView, state: ServiceState | null): string[] {
  const known = new Set(state?.capabilities.controllable_actions ?? []);
  const features = toy.features.filter((feature) => known.size === 0 || known.has(feature));
  return features.length ? features : ["Vibrate"];
}

export function onlineToys(state: ServiceState | null) {
  return (state?.toys ?? []).filter((toy) => toy.online);
}

export function needsSetup(state: ServiceState | null) {
  if (!state) return false;
  const anyTransport = state.transports.lan || state.transports.ble || state.transports.socket;
  return !anyTransport || state.toys.length === 0;
}
