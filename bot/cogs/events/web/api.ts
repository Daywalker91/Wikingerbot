import { apiFetch } from "@/api/client";
import type { SiteCategory } from "@/components/CategoryRoles";

export interface EventsSettings {
  channel_id: string | null;
  ping_role_id: string | null;
  native: boolean;
}

export interface EventRow {
  id: number;
  title: string;
  starts_at: string;
  cancelled: boolean;
  announce: boolean;
  posted: boolean;
  link: string | null;
}

export interface EventsData {
  settings: EventsSettings;
  text_channels: { id: string; name: string }[];
  roles: { id: string; name: string }[];
  can_manage_events: boolean;
  community_enabled: boolean;
  upcoming: EventRow[];
  error: string | null;
  categories: SiteCategory[];
  categories_error: string | null;
}

export const getEvents = () => apiFetch<EventsData>("/events/config");

export const saveEvents = (settings: EventsSettings) =>
  apiFetch<{ ok: boolean }>("/events/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });

export const syncEvent = (id: number) => apiFetch<{ done: string[] }>(`/events/${id}/sync`, { method: "POST" });
