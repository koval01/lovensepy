import { Activity, Loader2, Square } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useAsyncAction } from "@/hooks/use-async-action";
import { useNow } from "@/hooks/use-now";
import { useService } from "@/hooks/use-service";
import { api } from "@/lib/api";
import { formatSeconds, taskSubtitle, taskTitle } from "@/lib/format";
import type { TaskRow } from "@/lib/types";

/** Server-reported remaining time, minus the age of the snapshot it came from. */
function remainingNow(task: TaskRow, snapshotAt: number | null, now: number) {
  if (task.remaining_sec === null) return null;
  const age = snapshotAt ? (now - snapshotAt) / 1000 : 0;
  return Math.max(0, task.remaining_sec - age);
}

function SessionRow({ task, snapshotAt, now }: { task: TaskRow; snapshotAt: number | null; now: number }) {
  const { state, refresh } = useService();
  const toy = state?.toys.find((item) => item.id === task.toy_id);
  const remaining = remainingNow(task, snapshotAt, now);

  const [stop, stopping] = useAsyncAction(
    () => (task.toy_id ? api.command.stopToy(task.toy_id) : api.command.stopAll()),
    { errorTitle: "Stop failed", onDone: () => void refresh() },
  );

  const subtitle = taskSubtitle(task);

  return (
    <div className="flex items-center gap-3 py-3">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{taskTitle(task)}</p>
        <p className="text-muted-foreground truncate text-xs">
          {toy?.nick_name ?? (task.toy_id ? task.toy_id : "All devices")}
          {subtitle ? ` · ${subtitle}` : ""}
        </p>
      </div>
      <span className="text-muted-foreground shrink-0 font-mono text-xs tabular-nums">
        {formatSeconds(remaining)}
      </span>
      <Button variant="ghost" size="icon-sm" disabled={stopping} onClick={() => void stop()}>
        {stopping ? <Loader2 className="animate-spin" /> : <Square />}
        <span className="sr-only">Stop</span>
      </Button>
    </div>
  );
}

export function SessionsPanel() {
  const { state, lastUpdatedAt } = useService();
  const tasks = state?.tasks ?? [];
  const now = useNow(1_000, tasks.length > 0);

  if (tasks.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-2 py-10 text-center">
          <Activity className="text-muted-foreground size-8" />
          <p className="font-medium">Nothing is running</p>
          <p className="text-muted-foreground text-sm">
            Levels, presets and patterns you start show up here with their countdowns.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="divide-border divide-y">
        {tasks.map((task) => (
          <SessionRow key={task.task_id} task={task} snapshotAt={lastUpdatedAt} now={now} />
        ))}
      </CardContent>
    </Card>
  );
}
