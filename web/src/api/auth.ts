import { apiFetch } from "@/api/client";

export type Level = "member" | "mod" | "admin" | "owner";

export interface CurrentUser {
  // als Text - siehe api/types.py
  user_id: string;
  guild_id: string;
  level: Level;
  // Faehigkeiten wie "server.control" (bot/core/capabilities.py)
  capabilities?: string[];
}

export async function getMe(): Promise<CurrentUser> {
  return apiFetch<CurrentUser>("/auth/me");
}

export async function logout(): Promise<void> {
  await apiFetch<{ ok: boolean }>("/auth/logout", { method: "POST" });
}
