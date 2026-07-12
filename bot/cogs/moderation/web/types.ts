// Spiegelt bot/cogs/moderation/api.py's Pydantic-Modelle 1:1.
export interface ModLogEntryItem {
  id: number;
  user_id: number;
  mod_id: number;
  action: string;
  reason: string | null;
  duration: number | null;
  created_at: string;
}

export interface WarningItem {
  id: number;
  user_id: number;
  mod_id: number;
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
}

export interface MemberSearchResult {
  id: number;
  username: string;
  display_name: string;
}

export interface EscalationState {
  user_id: number;
  tier: number;
}
