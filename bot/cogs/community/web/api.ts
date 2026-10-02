import { apiFetch } from "@/api/client";

export interface CommunityStatus {
  db_name: string;
  site_url: string;
  enabled: boolean;
  db_host: string | null;
  connected: boolean;
  message: string;
  linked: number | null;
  pending: number | null;
  failed: number | null;
  handlers: string[];
}

export const getCommunity = () => apiFetch<CommunityStatus>("/community/config");

export const saveCommunity = (db_name: string, site_url: string) =>
  apiFetch<CommunityStatus>("/community/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ db_name, site_url }),
  });
