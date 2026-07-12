import { useEffect, useState } from "react";

import { useAuth } from "@/auth/useAuth";

import { getServers, startServer, stopServer } from "./api";
import { ServerConsole } from "./ServerConsole";
import type { ServerStatus } from "./types";

export const route = { path: "/servers", navLabel: "Server" };

const REFRESH_INTERVAL_MS = 15_000;
const CAN_MANAGE_LEVELS = ["mod", "admin", "owner"];

export default function ServerPage() {
  const { user } = useAuth();
  const canManage = user !== null && CAN_MANAGE_LEVELS.includes(user.level);

  const [servers, setServers] = useState<ServerStatus[] | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function load() {
    setServers(await getServers());
  }

  useEffect(() => {
    void load();
    const interval = setInterval(() => void load(), REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  async function handleStart(id: number) {
    const result = await startServer(id);
    setMessage(result.message);
    void load();
  }

  async function handleStop(id: number) {
    const result = await stopServer(id);
    setMessage(result.message);
    void load();
  }

  return (
    <main style={{ padding: 24 }}>
      <h1>Server</h1>
      {message && <p>{message}</p>}
      {servers === null && <p>Lädt…</p>}
      {servers !== null && servers.length === 0 && <p>Keine Server konfiguriert.</p>}

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {servers?.map((server) => (
          <div key={server.id} style={{ border: "1px solid #444", borderRadius: 8, padding: "12px 16px" }}>
            <strong>{server.display_name}</strong> ({server.instance_name})
            <div>
              {server.reachable ? (
                <>
                  {server.state}
                  {server.players && ` · Spieler: ${server.players[0]}/${server.players[1]}`}
                  {server.uptime && ` · Uptime: ${server.uptime}`}
                </>
              ) : (
                <span style={{ color: "#e74c3c" }}>Nicht erreichbar</span>
              )}
            </div>
            <div style={{ color: "#999", fontSize: "0.9em" }}>Verbinden: {server.host}</div>

            {canManage && (
              <div style={{ marginTop: 8 }}>
                <button onClick={() => void handleStart(server.id)} style={{ marginRight: 8 }}>
                  Start
                </button>
                <button onClick={() => void handleStop(server.id)} style={{ marginRight: 8 }}>
                  Stop
                </button>
                <button onClick={() => setExpanded(expanded === server.id ? null : server.id)}>
                  {expanded === server.id ? "Konsole schließen" : "Konsole"}
                </button>
              </div>
            )}

            {canManage && expanded === server.id && <ServerConsole serverId={server.id} />}
          </div>
        ))}
      </div>
    </main>
  );
}
