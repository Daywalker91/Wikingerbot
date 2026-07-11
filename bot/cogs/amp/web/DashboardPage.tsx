import { useEffect, useState } from "react";

import { getServers } from "./api";
import { ServerCard } from "./ServerCard";
import type { ServerStatus } from "./types";

export const route = { path: "/dashboard", navLabel: "Dashboard" };

const REFRESH_INTERVAL_MS = 15_000;

export default function DashboardPage() {
  const [servers, setServers] = useState<ServerStatus[] | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const data = await getServers();
      if (!cancelled) {
        setServers(data);
      }
    }

    void load();
    const interval = setInterval(() => void load(), REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return (
    <main style={{ padding: 24 }}>
      <h1>Dashboard</h1>
      {servers === null && <p>Lädt…</p>}
      {servers !== null && servers.length === 0 && <p>Keine Server konfiguriert.</p>}
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {servers?.map((server) => <ServerCard key={server.id} server={server} />)}
      </div>
    </main>
  );
}
