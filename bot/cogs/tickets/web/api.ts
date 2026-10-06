import { apiFetch } from "@/api/client";

export interface TicketRoute {
  channel_id: string | null;
  ping_role_id: string | null;
}

export interface TicketSettings {
  channel_id: string | null;
  ping_role_id: string | null;
  dm: boolean;
  routes: Record<string, TicketRoute>; // eigenes Forum/Ping je Kategorie
}

export interface OpenTicket {
  id: number;
  subject: string;
  status: string;
  author: string;
  assigned: string | null;
  has_thread: boolean;
  link: string | null;
}

export interface TicketsData {
  settings: TicketSettings;
  categories: { key: string; label: string }[];
  channels: { id: string; name: string; forum: boolean }[];
  roles: { id: string; name: string }[];
  community_enabled: boolean;
  open: OpenTicket[];
  error: string | null;
}

export const getTickets = () => apiFetch<TicketsData>("/tickets/config");

export const saveTickets = (settings: TicketSettings) =>
  apiFetch<{ ok: boolean }>("/tickets/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });

export const syncTicket = (id: number) => apiFetch<{ done: string[] }>(`/tickets/${id}/sync`, { method: "POST" });
