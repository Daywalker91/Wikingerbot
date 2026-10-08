import { apiFetch } from "@/api/client";
import type { SiteCategory } from "@/components/CategoryRoles";

export interface NewsSettings {
  channel_id: string | null;
  ping_role_id: string | null;
}

export interface NewsRow {
  id: number;
  title: string;
  published: boolean;
  announce: boolean;
  posted: boolean;
  link: string | null;
}

export interface NewsData {
  settings: NewsSettings;
  text_channels: { id: string; name: string }[];
  roles: { id: string; name: string }[];
  community_enabled: boolean;
  news_loaded: boolean;
  recent: NewsRow[];
  error: string | null;
  categories: SiteCategory[];
  categories_error: string | null;
}

export const getNews = () => apiFetch<NewsData>("/news/config");

export const saveNews = (settings: NewsSettings) =>
  apiFetch<{ ok: boolean }>("/news/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });

export const syncNews = (id: number) => apiFetch<{ done: string[] }>(`/news/${id}/sync`, { method: "POST" });
