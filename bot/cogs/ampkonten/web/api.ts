import { apiFetch } from "@/api/client";

export interface AmpRole {
  id: string;
  name: string;
}

export interface AmpKontenData {
  url: string;
  map: Record<string, string>;
  roles: AmpRole[];
  roles_fresh: boolean;
  amp_configured: boolean;
  loaded: boolean;
  community_enabled: boolean;
  ranks: { slug: string; name: string; level: number }[];
  requires: string;
  extra_roles: { slug: string; name: string }[];
  accounts: { member: string; amp_username: string; disabled: boolean; roles: string[] }[];
  error: string | null;
}

export const getAmpKonten = () => apiFetch<AmpKontenData>("/ampkonten/config");

export const saveAmpKonten = (url: string, map: Record<string, string | null>, requires: string) =>
  apiFetch<{ ok: boolean }>("/ampkonten/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, map, requires }),
  });

export const refreshRoles = () => apiFetch<{ roles: AmpRole[]; fresh: boolean }>("/ampkonten/refresh-roles", { method: "POST" });
