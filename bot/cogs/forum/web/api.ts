import { apiFetch } from "@/api/client";

export interface ForumSettings {
  channel_id: string | null;
  ping_role_id: string | null;
}

export interface ForumThreadRow {
  id: number;
  title: string;
  category: string;
  author: string | null;
  posted: boolean;
  link: string | null;
}

export interface ForumData {
  settings: ForumSettings;
  text_channels: { id: string; name: string }[];
  roles: { id: string; name: string }[];
  community_enabled: boolean;
  cog_loaded: boolean;
  recent: ForumThreadRow[];
  error: string | null;
}

export const getForum = () => apiFetch<ForumData>("/forum/config");

export const saveForum = (settings: ForumSettings) =>
  apiFetch<{ ok: boolean }>("/forum/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });

export const announceThread = (id: number) => apiFetch<{ done: string[] }>(`/forum/${id}/announce`, { method: "POST" });
