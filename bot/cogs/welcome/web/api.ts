import { apiFetch } from "@/api/client";

export interface WelcomeConfig {
  channel_id: string | null;
  message: string;
  dm_message: string;
  goodbye_enabled: boolean;
  goodbye_message: string;
  goodbye_channel_id: string | null;
}

export interface WelcomeData {
  config: WelcomeConfig;
  text_channels: { id: string; name: string }[];
  server_name: string;
  member_count: number;
}

export const getWelcome = () => apiFetch<WelcomeData>("/welcome");

export const saveWelcome = (config: WelcomeConfig) =>
  apiFetch<{ ok: boolean }>("/welcome", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
