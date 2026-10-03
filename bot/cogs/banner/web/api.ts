import { apiFetch } from "@/api/client";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";

export type BannerKind = "embed" | "image";
export type Background = "image" | "steam" | "theme" | "colors";

export interface Style {
  type: BannerKind;
  background: Background;
  theme: string;
  color_start: string | null;
  color_end: string | null;
  text_color: string | null;
  blur: number;
}

export interface ServerBanner extends Style {
  id: number;
  name: string;
  instance_name: string;
  enabled: boolean;
  channel_id: string | null;
  group_id: number | null;
  steam_art: boolean;
  has_image: boolean;
}

export interface GroupBanner extends Style {
  id: number;
  name: string;
  channel_id: string | null;
  layout: "combined" | "separate";
  member_ids: number[];
  has_image: boolean;
}

export interface BannerData {
  cog_loaded: boolean;
  text_channels: { id: string; name: string }[];
  themes: Record<string, [string, string]>;
  presets: Record<string, string>;
  blur_levels: Record<string, number>;
  max_group_members: number;
  servers: ServerBanner[];
  groups: GroupBanner[];
}

interface Result {
  ok: boolean;
  message: string;
  id?: number;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const getBanner = () => apiFetch<BannerData>("/banner/config");

export const saveServer = (id: number, body: Partial<ServerBanner>) => apiFetch<Result>(`/banner/servers/${id}`, json("PUT", body));
export const refreshServer = (id: number) => apiFetch<Result>(`/banner/servers/${id}/refresh`, { method: "POST" });

export const createGroup = (body: Partial<GroupBanner>) => apiFetch<Result>("/banner/groups", json("POST", body));
export const saveGroup = (id: number, body: Partial<GroupBanner>) => apiFetch<Result>(`/banner/groups/${id}`, json("PUT", body));
export const deleteGroup = (id: number) => apiFetch<Result>(`/banner/groups/${id}`, { method: "DELETE" });
export const refreshGroup = (id: number) => apiFetch<Result>(`/banner/groups/${id}/refresh`, { method: "POST" });

export function uploadBackground(kind: "servers" | "groups", id: number, file: File) {
  return apiFetch<Result>(`/banner/${kind}/${id}/background`, {
    method: "POST",
    headers: { "Content-Type": file.type },
    body: file,
  });
}

/** Vorschau-Bild als Object-URL (mit Session-Cookie geladen). */
export async function previewUrl(kind: "servers" | "groups", id: number, style: Style, members?: number[]): Promise<string> {
  const params = new URLSearchParams({ background: style.background, theme: style.theme, blur: String(style.blur) });
  if (style.color_start) params.set("color_start", style.color_start);
  if (style.color_end) params.set("color_end", style.color_end);
  if (style.text_color) params.set("text_color", style.text_color);
  if (members) params.set("members", members.join(","));
  const response = await fetch(`${API_BASE_URL}/banner/${kind}/${id}/preview?${params.toString()}`, { credentials: "include" });
  if (!response.ok) throw new Error(`Vorschau nicht möglich (${response.status})`);
  return URL.createObjectURL(await response.blob());
}
