// Spiegelt bot/cogs/whitelist/api.py's WhitelistRequestOut 1:1.
// Discord-IDs sind Text (siehe api/types.py) - als Zahl wuerde JavaScript sie runden.
export type WhitelistStatus = "pending" | "approved" | "denied" | "revoked";

export interface WhitelistRequestItem {
  id: number;
  user_id: string;
  server_id: number;
  server_name: string;
  ign: string;
  status: WhitelistStatus;
  created_at: string;
  handled_by: string | null;
}

export interface ActionResult {
  ok: boolean;
  message: string;
}
