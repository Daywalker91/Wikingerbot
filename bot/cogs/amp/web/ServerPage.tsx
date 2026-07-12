import { useEffect, useState } from "react";

import { useAuth } from "@/auth/useAuth";

import { createServer, getDiscoverableInstances, getServers, startServer, stopServer } from "./api";
import { ServerConsole } from "./ServerConsole";
import type { DiscoverableInstance, ServerStatus } from "./types";

export const route = { path: "/servers", navLabel: "Server" };

const REFRESH_INTERVAL_MS = 15_000;
const CAN_MANAGE_LEVELS = ["mod", "admin", "owner"];

export default function ServerPage() {
  const { user } = useAuth();
  const canManage = user !== null && CAN_MANAGE_LEVELS.includes(user.level);
  const isOwner = user?.level === "owner";

  const [servers, setServers] = useState<ServerStatus[] | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const [discoverable, setDiscoverable] = useState<DiscoverableInstance[]>([]);
  const [newInstanceId, setNewInstanceId] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [newHost, setNewHost] = useState("");
  const [showAddForm, setShowAddForm] = useState(false);

  async function load() {
    setServers(await getServers());
  }

  useEffect(() => {
    void load();
    const interval = setInterval(() => void load(), REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (isOwner && showAddForm) {
      void getDiscoverableInstances().then((instances) => {
        setDiscoverable(instances);
        if (instances.length > 0) {
          setNewInstanceId(instances[0].instance_id);
          if (!newDisplayName) setNewDisplayName(instances[0].friendly_name);
        }
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOwner, showAddForm]);

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

  async function handleCreateServer() {
    if (!newInstanceId || !newDisplayName || !newHost) return;
    const instance = discoverable.find((i) => i.instance_id === newInstanceId);
    await createServer({
      instance_name: instance?.friendly_name.replace(/\s+/g, "") ?? newInstanceId,
      amp_instance_id: newInstanceId,
      display_name: newDisplayName,
      host: newHost,
    });
    setNewDisplayName("");
    setNewHost("");
    setShowAddForm(false);
    void load();
  }

  const filteredServers = servers?.filter((server) => {
    const term = search.toLowerCase();
    return (
      server.display_name.toLowerCase().includes(term) ||
      server.instance_name.toLowerCase().includes(term) ||
      server.host.toLowerCase().includes(term)
    );
  });

  return (
    <main style={{ padding: 24 }}>
      <h1>Server</h1>
      {message && <p>{message}</p>}

      <div style={{ marginBottom: 16, display: "flex", gap: 12, alignItems: "center" }}>
        <input
          placeholder="Suche nach Name oder Adresse…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: 260 }}
        />
        {isOwner && (
          <button onClick={() => setShowAddForm((v) => !v)}>
            {showAddForm ? "Abbrechen" : "Neuen Server anlegen"}
          </button>
        )}
      </div>

      {isOwner && showAddForm && (
        <div
          style={{
            border: "1px solid #444",
            borderRadius: 8,
            padding: "12px 16px",
            marginBottom: 16,
          }}
        >
          <div style={{ marginBottom: 8 }}>
            <select value={newInstanceId} onChange={(e) => setNewInstanceId(e.target.value)}>
              {discoverable.length === 0 && <option value="">Keine neuen AMP-Instanzen gefunden</option>}
              {discoverable.map((instance) => (
                <option key={instance.instance_id} value={instance.instance_id}>
                  {instance.friendly_name} ({instance.module})
                </option>
              ))}
            </select>
          </div>
          <div style={{ marginBottom: 8 }}>
            <input
              placeholder="Anzeigename"
              value={newDisplayName}
              onChange={(e) => setNewDisplayName(e.target.value)}
              style={{ marginRight: 8 }}
            />
            <input
              placeholder="Verbindungs-Adresse (Host)"
              value={newHost}
              onChange={(e) => setNewHost(e.target.value)}
            />
          </div>
          <button onClick={() => void handleCreateServer()}>Anlegen</button>
        </div>
      )}

      {servers === null && <p>Lädt…</p>}
      {servers !== null && servers.length === 0 && <p>Keine Server konfiguriert.</p>}
      {servers !== null && servers.length > 0 && filteredServers?.length === 0 && (
        <p>Keine Server passen zur Suche.</p>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {filteredServers?.map((server) => (
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
