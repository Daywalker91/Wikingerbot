import { apiFetch } from "@/api/client";

import type { ConsoleLineItem, ServerActionResult, ServerStatus } from "./types";

export async function getServers(): Promise<ServerStatus[]> {
  return apiFetch<ServerStatus[]>("/servers");
}

export async function startServer(id: number): Promise<ServerActionResult> {
  return apiFetch<ServerActionResult>(`/servers/${id}/start`, { method: "POST" });
}

export async function stopServer(id: number): Promise<ServerActionResult> {
  return apiFetch<ServerActionResult>(`/servers/${id}/stop`, { method: "POST" });
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
