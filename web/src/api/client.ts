// Lokal (npm run dev) zeigt VITE_API_BASE_URL auf uvicorn; im fertigen Build
// liefert der Bot Seite und API selbst aus, die API liegt dann unter /api.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/**
 * Gemeinsamer fetch-Wrapper fuer alle API-Aufrufe (zentral + Cog-Seiten).
 * credentials:"include" ist noetig, damit der httpOnly Session-Cookie bei
 * Cross-Origin-Requests (Frontend/Backend auf unterschiedlichen Ports)
 * mitgeschickt wird - siehe CORS-Konfiguration in api/main.py.
 */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    // FastAPI liefert {"detail": "..."} - die Meldung ist fuer den Nutzer gedacht
    let message = `${init?.method ?? "GET"} ${path} -> ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      // kein JSON - Standardmeldung behalten
    }
    throw new ApiError(response.status, message);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export function loginUrl(guildId: string): string {
  return `${API_BASE_URL}/auth/login?guild_id=${encodeURIComponent(guildId)}`;
}
