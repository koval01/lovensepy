import { toast } from "sonner";
import { useEffect, useRef } from "react";

import { useService } from "@/hooks/use-service";
import { api } from "@/lib/api";
import type { PendingAccessApproval } from "@/lib/types";

function describeVisitor(row: PendingAccessApproval) {
  const who = [row.device, row.browser].filter(Boolean).join(" · ") || "Unknown device";
  const where = [row.ip, row.country].filter(Boolean).join(" · ");
  return where ? `${who} · ${where}` : who;
}

/**
 * Host-only: when a Cloudflare visitor is waiting, prompt Allow / Deny in the local panel.
 */
export function AccessApprovalToasts() {
  const { state, role, refresh } = useService();
  const seenRef = useRef<Set<string>>(new Set());
  const isHost = role !== "remote";
  const pending = state?.gate?.pending_approvals ?? [];
  const pendingKey = pending.map((row) => row.id).join("|");

  useEffect(() => {
    if (!isHost) return;

    const live = new Set(pending.map((row) => row.id));
    for (const id of [...seenRef.current]) {
      if (!live.has(id)) {
        toast.dismiss(`access-approval-${id}`);
        seenRef.current.delete(id);
      }
    }

    for (const row of pending) {
      const toastId = `access-approval-${row.id}`;
      if (seenRef.current.has(row.id)) continue;
      seenRef.current.add(row.id);

      toast("Allow this user to connect?", {
        id: toastId,
        description: describeVisitor(row),
        duration: Infinity,
        action: {
          label: "Allow",
          onClick: () => {
            void api.accessApprovals
              .allow(row.id)
              .then(() => {
                toast.success("Remote access allowed", { description: describeVisitor(row) });
                void refresh(true);
              })
              .catch((cause: unknown) => {
                toast.error(cause instanceof Error ? cause.message : "Could not allow access");
              });
          },
        },
        cancel: {
          label: "Deny",
          onClick: () => {
            void api.accessApprovals
              .deny(row.id)
              .then(() => {
                toast.message("Remote access denied", { description: describeVisitor(row) });
                void refresh(true);
              })
              .catch((cause: unknown) => {
                toast.error(cause instanceof Error ? cause.message : "Could not deny access");
              });
          },
        },
      });
    }
    // pendingKey tracks membership; pending rows are read from the latest render.
  }, [isHost, pending, pendingKey, refresh]);

  return null;
}
