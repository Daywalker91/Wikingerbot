import { apiFetch } from "@/api/client";

import type {
  AddressSettings,
  ConsoleLineItem,
  DiscoverableInstance,
  ServerActionResult,
  ServerCreateBody,
  ServerStatus,
} from "./types";

export async function getServers(): Promise<ServerStatus[]> {
  return apiFetch<ServerStatus[]>("/servers");
}

export interface DiscordRole {
  id: string;
  name: string;
  above_bot: boolean;
}

export async function getDiscordRoles(): Promise<DiscordRole[]> {
  return apiFetch<DiscordRole[]>("/servers/discord-roles");
}

export async function saveWhitelist(id: number, enabled: boolean, roleId: string | null): Promise<ServerActionResult> {
  return apiFetch<ServerActionResult>(`/servers/${id}/whitelist`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled, role_id: roleId }),
  });
}

export async function getDiscoverableInstances(): Promise<DiscoverableInstance[]> {
  return apiFetch<DiscoverableInstance[]>("/servers/discoverable");
}

export async function createServer(body: ServerCreateBody): Promise<ServerStatus> {
  return apiFetch<ServerStatus>("/servers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function getAddressSettings(): Promise<AddressSettings> {
  return apiFetch<AddressSettings>("/servers/address-settings");
}

export async function saveAddressSettings(gameHost: string): Promise<{ game_host: string }> {
  return apiFetch<{ game_host: string }>("/servers/address-settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ game_host: gameHost }),
  });
}

export async function startServer(id: number): Promise<ServerActionResult> {
  return apiFetch<ServerActionResult>(`/servers/${id}/start`, { method: "POST" });
}

export async function stopServer(id: number): Promise<ServerActionResult> {
  return apiFetch<ServerActionResult>(`/servers/${id}/stop`, { method: "POST" });
}

export async function deleteServer(id: number): Promise<ServerActionResult> {
  return apiFetch<ServerActionResult>(`/servers/${id}`, { method: "DELETE" });
}

export async function getConsole(id: number): Promise<ConsoleLineItem[]> {
  return apiFetch<ConsoleLineItem[]>(`/servers/${id}/console`);
}

export async function sendConsoleCommand(id: number, command: string): Promise<ServerActionResult> {
  return apiFetch<ServerActionResult>(`/servers/${id}/console`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command }),
  });
}
