import { apiFetch } from "@/api/client";

export interface AutoModRules {
  enabled: boolean;
  flood: { on: boolean; messages: number; seconds: number };
  duplicates: { on: boolean; count: number; seconds: number };
  caps: { on: boolean; percent: number; min_length: number };
  emojis: { on: boolean; max: number };
  links: { mode: "off" | "allowlist" | "block"; allow: string[] };
  new_accounts_days: number;
  action: { delete: boolean; points: number; timeout_minutes: number };
  exempt_channels: string[];
  exempt_roles: string[];
}

export interface AutoModConfig {
  discord: { enabled: boolean; points: Record<string, number> };
  rules: AutoModRules;
  alert_channel_id: string | null;
}

export interface AutoModData {
  config: AutoModConfig;
  trigger_labels: Record<string, string>;
  text_channels: { id: string; name: string }[];
  roles: { id: string; name: string }[];
  moderation_loaded: boolean;
}

export const getAutoMod = () => apiFetch<AutoModData>("/automod/config");

export const saveAutoMod = (config: AutoModConfig) =>
  apiFetch<{ ok: boolean }>("/automod/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
