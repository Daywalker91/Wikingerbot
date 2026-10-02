import { apiFetch } from "@/api/client";

export type Direction = "both" | "to_site" | "to_discord" | "off";

export interface RankRow {
  slug: string;
  name: string;
  level: number;
  role_id: string | null;
  suggested_role_id: string | null;
  direction: Direction;
  is_king: boolean;
}

export interface RangsyncData {
  enabled: boolean;
  community_enabled: boolean;
  roles: { id: string; name: string; above_bot: boolean }[];
  ranks: RankRow[];
  ticket_owner: number | null;
  owners: { id: number; name: string }[];
  error: string | null;
}

export const getRangsync = () => apiFetch<RangsyncData>("/rangsync/config");

export const saveRangsync = (body: {
  enabled: boolean;
  ranks: Record<string, { role_id: string | null; direction: Direction }>;
  ticket_owner: number | null;
}) =>
  apiFetch<{ ok: boolean }>("/rangsync/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const syncAll = () => apiFetch<{ result: Record<string, number> }>("/rangsync/sync-all", { method: "POST" });
