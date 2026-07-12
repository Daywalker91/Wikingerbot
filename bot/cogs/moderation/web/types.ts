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

export interface AutoModPoints {
  spam: number;
  keyword: number;
  keyword_preset: number;
  mention_spam: number;
  harmful_link: number;
  member_profile: number;
}

export interface ModConfig {
  warn_threshold: number;
  warn_ladder: LadderAction[];
  warn_timeout_minutes: number;
  warn_decay_days: number;
  automod_warn_enabled: boolean;
  automod_warn_points: AutoModPoints;
  automod_alert_channel_id: number | null;
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

export interface TextChannelItem {
  id: number;
  name: string;
}
