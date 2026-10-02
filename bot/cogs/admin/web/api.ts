import { apiFetch } from "@/api/client";

import type { CogsStatus, DiscordRoleItem, GuildRoleItem, PermissionLevel } from "./types";

export async function getDiscordRoles(): Promise<DiscordRoleItem[]> {
  return apiFetch<DiscordRoleItem[]>("/admin/discord-roles");
}

export async function getGuildRoles(): Promise<GuildRoleItem[]> {
  return apiFetch<GuildRoleItem[]>("/admin/roles");
}

export async function addGuildRole(discordRoleId: string, level: PermissionLevel): Promise<GuildRoleItem> {
  return apiFetch<GuildRoleItem>("/admin/roles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ discord_role_id: discordRoleId, level }),
  });
}

export async function removeGuildRole(id: number): Promise<void> {
  await apiFetch<{ ok: boolean }>(`/admin/roles/${id}`, { method: "DELETE" });
}

export async function getCogsStatus(): Promise<CogsStatus> {
  return apiFetch<CogsStatus>("/admin/cogs");
}
