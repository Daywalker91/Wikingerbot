import { apiFetch } from "@/api/client";

import type { ControlAction, EpisodeItem, Library, MusicConfig, MusicState, PlayKind } from "./types";

const json = (body: unknown) => ({
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const getState = () => apiFetch<MusicState>("/music/state");
export const getLibrary = () => apiFetch<Library>("/music/library");
export const getEpisodes = (name: string) =>
  apiFetch<EpisodeItem[]>(`/music/podcasts/${encodeURIComponent(name)}/episodes`);

export const play = (kind: PlayKind, name: string, episode = 0, shuffle = false) =>
  apiFetch<{ added: number }>("/music/play", { method: "POST", ...json({ kind, name, episode, shuffle }) });

export const control = (action: ControlAction, value?: number) =>
  apiFetch<{ ok: boolean }>("/music/control", { method: "POST", ...json({ action, value }) });

export const getConfig = () => apiFetch<MusicConfig>("/music/config");
export const addStation = (name: string, url: string) =>
  apiFetch("/music/stations", { method: "POST", ...json({ name, url }) });
export const importStations = (url: string) =>
  apiFetch<{ message: string }>("/music/stations/import", { method: "POST", ...json({ url }) });
export const removeStation = (name: string) =>
  apiFetch(`/music/stations/${encodeURIComponent(name)}`, { method: "DELETE" });
export const addPodcast = (name: string, url: string) =>
  apiFetch<{ title: string; episodes: number }>("/music/podcasts", { method: "POST", ...json({ name, url }) });
export const removePodcast = (name: string) =>
  apiFetch(`/music/podcasts/${encodeURIComponent(name)}`, { method: "DELETE" });
export const setAnnounce = (name: string, channelId: string | null) =>
  apiFetch(`/music/podcasts/${encodeURIComponent(name)}/announce`, {
    method: "PUT",
    ...json({ channel_id: channelId }),
  });
