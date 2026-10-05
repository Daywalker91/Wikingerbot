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

export interface TierPlan {
  allow: string[];
  neutral: string[];
  missing: string[];
  error?: string;
}

export interface SetupReport {
  controller: {
    login?: string[];
    instances?: Record<string, string[]>;
    missing_instances?: string[];
    admin?: string[];
    verwalter?: string[];
    other_nodes?: string[];
  };
  instances: Record<string, Record<string, TierPlan> & { error?: string }>;
  created_roles: string[];
  changed: number;
  errors: string[];
  skipped?: string[];
}

export interface RolesStatus {
  tiers: { key: string; name: string; caps: string[] }[];
  pending: string[];
  outdated?: string[];
  done: string[];
}

export const getRolesStatus = () => apiFetch<RolesStatus>("/ampkonten/roles/status");
export interface AdminLogin {
  username: string;
  password: string;
  token: string;
}

const withLogin = (login: AdminLogin | null): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(login ?? {}),
});

// redo: auch schon eingerichtete Instanzen erneut (sonst nur die offenen)
export const checkRoles = (login: AdminLogin | null, redo = false) =>
  apiFetch<SetupReport>(`/ampkonten/roles/check?redo=${redo}`, withLogin(login));
export const applyRoles = (login: AdminLogin | null, redo = false) =>
  apiFetch<SetupReport>(`/ampkonten/roles/apply?redo=${redo}`, withLogin(login));
