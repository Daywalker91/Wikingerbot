import { apiFetch } from "@/api/client";

import type { ActionResult, ModLogEntryItem, WarningItem } from "./types";

export async function getModLog(): Promise<ModLogEntryItem[]> {
  return apiFetch<ModLogEntryItem[]>("/moderation/modlog");
}

export async function getWarnings(): Promise<WarningItem[]> {
  return apiFetch<WarningItem[]>("/moderation/warnings");
}

export async function unbanUser(userId: string, reason: string): Promise<ActionResult> {
  return apiFetch<ActionResult>("/moderation/unban", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: Number(userId), reason }),
  });
}
