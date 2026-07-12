import { useEffect, useState } from "react";

import { getModLog, getWarnings, unbanUser } from "./api";
import type { ModLogEntryItem, WarningItem } from "./types";

export const route = { path: "/moderation", navLabel: "Moderation" };

export default function ModerationPage() {
  const [modlog, setModlog] = useState<ModLogEntryItem[] | null>(null);
  const [warnings, setWarnings] = useState<WarningItem[] | null>(null);
  const [unbanUserId, setUnbanUserId] = useState("");
  const [unbanReason, setUnbanReason] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  async function load() {
    const [modlogResult, warningsResult] = await Promise.all([getModLog(), getWarnings()]);
    setModlog(modlogResult);
    setWarnings(warningsResult);
  }

  useEffect(() => {
    void load();
  }, []);

  async function handleUnban() {
    if (!unbanUserId) return;
    const result = await unbanUser(unbanUserId, unbanReason || "Kein Grund angegeben");
    setMessage(result.message);
    setUnbanUserId("");
    setUnbanReason("");
    void load();
  }

  return (
    <main style={{ padding: 24 }}>
      <h1>Moderation</h1>

      <section style={{ marginBottom: 32 }}>
        <h2>Bann aufheben</h2>
        <input
          placeholder="User-ID"
          value={unbanUserId}
          onChange={(e) => setUnbanUserId(e.target.value)}
          style={{ marginRight: 8 }}
        />
        <input
          placeholder="Begründung"
          value={unbanReason}
          onChange={(e) => setUnbanReason(e.target.value)}
          style={{ marginRight: 8 }}
        />
        <button onClick={() => void handleUnban()}>Entbannen</button>
        {message && <p>{message}</p>}
      </section>

      <section style={{ marginBottom: 32 }}>
        <h2>ModLog</h2>
        {modlog === null && <p>Lädt…</p>}
        {modlog !== null && modlog.length === 0 && <p>Keine Einträge.</p>}
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {modlog?.map((entry) => (
            <div key={entry.id} style={{ border: "1px solid #444", borderRadius: 8, padding: "8px 12px" }}>
              <strong>{entry.action}</strong> — Nutzer {entry.user_id} von Mod {entry.mod_id}
              <div style={{ color: "#999", fontSize: "0.9em" }}>
                {new Date(entry.created_at).toLocaleString()} · {entry.reason ?? "-"}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2>Aktive Verwarnungen</h2>
        {warnings === null && <p>Lädt…</p>}
        {warnings !== null && warnings.length === 0 && <p>Keine aktiven Verwarnungen.</p>}
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {warnings?.map((warning) => (
            <div key={warning.id} style={{ border: "1px solid #444", borderRadius: 8, padding: "8px 12px" }}>
              Nutzer {warning.user_id} — {warning.points} Punkt(e) von Mod {warning.mod_id}
              <div style={{ color: "#999", fontSize: "0.9em" }}>
                {new Date(warning.created_at).toLocaleString()} · {warning.reason ?? "-"}
              </div>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
