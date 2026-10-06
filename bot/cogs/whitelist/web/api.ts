import { apiFetch } from "@/api/client";

import type { ActionResult, WhitelistRequestItem, WhitelistStatus } from "./types";

export async function getRequests(status: WhitelistStatus): Promise<WhitelistRequestItem[]> {
  return apiFetch<WhitelistRequestItem[]>(`/whitelist/requests?status=${status}`);
}

export async function approveRequest(id: number): Promise<ActionResult> {
  return apiFetch<ActionResult>(`/whitelist/requests/${id}/approve`, { method: "POST" });
}

export async function revokeRequest(id: number, reason?: string): Promise<ActionResult> {
  return apiFetch<ActionResult>(`/whitelist/requests/${id}/revoke`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason: reason ?? null }),
  });
}

export async function denyRequest(id: number, reason?: string): Promise<ActionResult> {
  return apiFetch<ActionResult>(`/whitelist/requests/${id}/deny`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason: reason ?? null }),
  });
}

// Gruppen-Rollen (Panel-Knopf mit Bestaetigung) - wie Whitelist-Anfragen, ohne Server
export interface GroupRequestItem {
  id: number;
  user_id: string;
  user_name: string | null;
  role_id: string;
  role_name: string;
  status: "pending" | "approved" | "denied" | "revoked" | "cancelled";
  note: string | null;
  decided_by: string | null;
  created_at: string;
}

export async function getGroupRequests(status: WhitelistStatus): Promise<GroupRequestItem[]> {
  return apiFetch<GroupRequestItem[]>(`/whitelist/groups?status=${status}`);
}

const groupAction = (id: number, action: "approve" | "deny" | "revoke", reason?: string) =>
  apiFetch<ActionResult>(`/whitelist/groups/${id}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: action === "approve" ? undefined : JSON.stringify({ reason: reason ?? null }),
  });

export const approveGroup = (id: number) => groupAction(id, "approve");
export const denyGroup = (id: number, reason?: string) => groupAction(id, "deny", reason);
export const revokeGroup = (id: number, reason?: string) => groupAction(id, "revoke", reason);
