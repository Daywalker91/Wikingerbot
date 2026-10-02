// Spiegelt bot/cogs/admin/api.py's Pydantic-Modelle 1:1.
export type PermissionLevel = "member" | "mod" | "admin" | "owner";

// Discord-IDs sind Text (siehe api/types.py) - als Zahl wuerde JavaScript sie runden.
export interface DiscordRoleItem {
  id: string;
  name: string;
}

export interface GuildRoleItem {
  id: number;
  discord_role_id: string;
  level: PermissionLevel;
}

export interface CogsStatus {
  available: string[];
  loaded: string[];
}
