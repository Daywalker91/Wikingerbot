import { apiFetch } from "@/api/client";

import type { ActionResult, WhitelistRequestItem, WhitelistStatus } from "./types";

export async function getRequests(status: WhitelistStatus): Promise<WhitelistRequestItem[]> {
  return apiFetch<WhitelistRequestItem[]>(`/whitelist/requests?status=${status}`);
}

export async function approveRequest(id: number): Promise<ActionResult> {
  return apiFetch<ActionResult>(`/whitelist/requests/${id}/approve`, { method: "POST" });
}

export async function denyRequest(id: number, reason?: string): Promise<ActionResult> {
  return apiFetch<ActionResult>(`/whitelist/requests/${id}/deny`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason: reason ?? null }),
  });
}
