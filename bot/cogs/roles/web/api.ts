import { apiFetch } from "@/api/client";

export interface RoleItem {
  id: string;
  name: string;
  color: string | null;
  blocked: string | null;
}

export interface PanelButton {
  role_id: string;
  label: string;
  emoji: string;
  confirm?: boolean; // Klick = Anfrage, das Team bestaetigt (wie eine Whitelist-Anfrage)
}

export interface Panel {
  channel_id: string;
  channel_name: string | null;
  message_id: string;
  missing: boolean;
  url: string | null;
  title: string;
  text: string;
  buttons: PanelButton[];
}

export interface RolesData {
  cog_loaded: boolean;
  text_channels: { id: string; name: string }[];
  roles: RoleItem[];
  autoroles: string[];
  panels: Panel[];
  max_buttons: number;
}

interface Result {
  ok: boolean;
  message: string;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const getRoles = () => apiFetch<RolesData>("/roles/config");
export const saveAutoroles = (roleIds: string[]) => apiFetch<Result>("/roles/autoroles", json("PUT", { role_ids: roleIds }));
export const createPanel = (body: { channel_id: string; title: string; text: string; buttons: PanelButton[] }) =>
  apiFetch<Result>("/roles/panels", json("POST", body));
export const savePanel = (messageId: string, body: { title: string; text: string; buttons: PanelButton[] }) =>
  apiFetch<Result>(`/roles/panels/${messageId}`, json("PUT", body));
export const deletePanel = (messageId: string) => apiFetch<Result>(`/roles/panels/${messageId}`, { method: "DELETE" });
export const adoptPanel = (link: string) => apiFetch<Result>("/roles/panels/adopt", json("POST", { link }));
