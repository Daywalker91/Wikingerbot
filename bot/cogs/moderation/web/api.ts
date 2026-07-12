import { apiFetch } from "@/api/client";

import type { ActionResult, MemberSearchResult, ModConfig, ModLogEntryItem, WarningItem } from "./types";

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

export async function banUser(
  userId: string,
  reason: string,
  deleteMessageDays: number,
): Promise<ActionResult> {
  return apiFetch<ActionResult>("/moderation/ban", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: Number(userId),
      reason,
      delete_message_days: deleteMessageDays,
    }),
  });
}

export async function getModConfig(): Promise<ModConfig> {
  return apiFetch<ModConfig>("/moderation/mod-config");
}

export async function updateModConfig(config: ModConfig): Promise<ModConfig> {
  return apiFetch<ModConfig>("/moderation/mod-config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
}

export async function searchMembers(query: string): Promise<MemberSearchResult[]> {
  if (!query) return [];
  return apiFetch<MemberSearchResult[]>(`/moderation/member-search?query=${encodeURIComponent(query)}`);
}
