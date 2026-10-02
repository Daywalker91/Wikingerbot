// Spiegelt bot/cogs/moderation/api.py's Pydantic-Modelle 1:1.
// Discord-IDs sind Text (siehe api/types.py) - als Zahl wuerde JavaScript sie runden.
export interface ModLogEntryItem {
  id: number;
  user_id: string;
  mod_id: string;
  action: string;
  reason: string | null;
  duration: number | null;
  created_at: string;
}

export interface WarningItem {
  id: number;
  user_id: string;
  mod_id: string;
  reason: string | null;
  points: number;
  created_at: string;
}

export interface ActionResult {
  ok: boolean;
  message: string;
}

export type LadderAction = "timeout" | "ban" | "kick";

export interface ModConfig {
  warn_threshold: number;
  warn_ladder: LadderAction[];
  warn_timeout_minutes: number;
  warn_decay_days: number;
  modlog_channel_id: string | null;
}

export interface MemberSearchResult {
  id: string;
  username: string;
  display_name: string;
}

export interface EscalationState {
  user_id: string;
  tier: number;
}

export interface TextChannelItem {
  id: string;
  name: string;
}
