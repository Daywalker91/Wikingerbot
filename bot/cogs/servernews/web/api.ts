import { apiFetch } from "@/api/client";

export interface ServerNewsSettings {
  channel_id: string | null;
  ping_role_id: string | null;
  leads: string; // z.B. "30, 10, 1"
  amp_schedule: boolean;
  outages: boolean;
}

export interface ServerNewsData {
  settings: ServerNewsSettings;
  servers: { id: number; name: string; ingame: string; suggestion: string }[];
  text_channels: { id: string; name: string }[];
  roles: { id: string; name: string }[];
  cog_loaded: boolean;
}

export interface Notice {
  id: number;
  server: string;
  kind: string;
  origin: "manual" | "amp";
  status: string;
  at: number; // Unix-Sekunden
  duration_min: number | null;
  reason: string | null;
}

export interface AmpPreview {
  now: string;
  servers: { server: string; runs: { kind: string; label: string; at: string }[]; error: string | null }[];
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const getServerNews = () => apiFetch<ServerNewsData>("/servernews/config");
export const saveServerNews = (settings: ServerNewsSettings, ingame: Record<string, string>) =>
  apiFetch<{ message: string }>("/servernews/config", json("PUT", { ...settings, ingame }));
export const testIngame = (serverId: number, command: string) =>
  apiFetch<{ message: string }>(`/servernews/servers/${serverId}/test`, json("POST", { command }));
export const getAmpPreview = () => apiFetch<AmpPreview>("/servernews/amp-preview");
export const getNotices = () => apiFetch<Notice[]>("/servernews/notices");
export const addNotice = (body: { server_id: number; kind: string; start: string; duration_min: number | null; reason: string | null }) =>
  apiFetch<{ message: string }>("/servernews/notices", json("POST", body));
export const cancelNotice = (id: number) => apiFetch<{ message: string }>(`/servernews/notices/${id}/cancel`, { method: "POST" });
