import { apiFetch } from "@/api/client";

export interface RoleRequestRow {
  id: number;
  member: string;
  rank: string;
  role: string;
  kind: "rank" | "extra";
  status: "pending" | "approved" | "denied" | "cancelled";
  reason: string;
  decided_by: string | null;
  note: string | null;
  created_at: string | null;
  ticket_link: string | null;
}

export interface RoleRequestsData {
  community_enabled: boolean;
  cog_loaded: boolean;
  modlog_set: boolean;
  requests: RoleRequestRow[];
  error: string | null;
}

export const getRoleRequests = () => apiFetch<RoleRequestsData>("/rollenanfragen");
