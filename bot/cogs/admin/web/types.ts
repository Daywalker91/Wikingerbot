// Spiegelt bot/cogs/admin/api.py's Pydantic-Modelle 1:1.
export type PermissionLevel = "member" | "mod" | "admin" | "owner";

export interface DiscordRoleItem {
  id: number;
  name: string;
}

export interface GuildRoleItem {
  id: number;
  discord_role_id: number;
  level: PermissionLevel;
}

export interface CogsStatus {
  available: string[];
  loaded: string[];
}
