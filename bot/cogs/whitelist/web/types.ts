// Spiegelt bot/cogs/whitelist/api.py's WhitelistRequestOut 1:1.
export type WhitelistStatus = "pending" | "approved" | "denied";

export interface WhitelistRequestItem {
  id: number;
  user_id: number;
  server_id: number;
  server_name: string;
  ign: string;
  status: WhitelistStatus;
  created_at: string;
  handled_by: number | null;
}

export interface ActionResult {
  ok: boolean;
  message: string;
}
