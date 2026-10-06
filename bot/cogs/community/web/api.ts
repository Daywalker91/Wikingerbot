import { apiFetch } from "@/api/client";

export interface CommunityStatus {
  db_name: string;
  site_url: string;
  enabled: boolean;
  db_host: string | null;
  own_host: string;
  own_port: number | null;
  own_user: string;
  password_set: boolean;
  connected: boolean;
  message: string;
  linked: number | null;
  pending: number | null;
  failed: number | null;
  handlers: string[];
}

export const getCommunity = () => apiFetch<CommunityStatus>("/community/config");

export interface CommunityConfigIn {
  db_name: string;
  site_url: string;
  host: string;
  port: number | null;
  user: string;
  password: string | null; // null/leer = unveraendert
  clear_password: boolean;
}

export const saveCommunity = (config: CommunityConfigIn) =>
  apiFetch<CommunityStatus>("/community/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
