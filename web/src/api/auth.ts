import { apiFetch } from "@/api/client";

export type Level = "member" | "mod" | "admin" | "owner";

export interface CurrentUser {
  user_id: number;
  guild_id: number;
  level: Level;
}

export async function getMe(): Promise<CurrentUser> {
  return apiFetch<CurrentUser>("/auth/me");
}

export async function logout(): Promise<void> {
  await apiFetch<{ ok: boolean }>("/auth/logout", { method: "POST" });
}
