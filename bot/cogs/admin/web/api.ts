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

export interface CapabilityItem {
  key: string;
  label: string;
  default: PermissionLevel;
  role_ids: string[];
}

export async function getCapabilities(): Promise<CapabilityItem[]> {
  return apiFetch<CapabilityItem[]>("/admin/capabilities");
}

export async function saveCapabilities(roles: Record<string, string[]>): Promise<{ message: string }> {
  return apiFetch<{ message: string }>("/admin/capabilities", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ roles }),
  });
}

export async function getCogsStatus(): Promise<CogsStatus> {
  return apiFetch<CogsStatus>("/admin/cogs");
}

export async function changeCog(name: string, action: "load" | "unload" | "reload"): Promise<{ message: string }> {
  return apiFetch<{ message: string }>(`/admin/cogs/${encodeURIComponent(name)}/${action}`, { method: "POST" });
}
