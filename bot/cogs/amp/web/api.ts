import { apiFetch } from "@/api/client";

import type { ServerStatus } from "./types";

export async function getServers(): Promise<ServerStatus[]> {
  return apiFetch<ServerStatus[]>("/servers");
}
