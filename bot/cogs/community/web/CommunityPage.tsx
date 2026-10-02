import { useEffect, useState, type CSSProperties } from "react";

import { useAuth } from "@/auth/useAuth";

import { getCommunity, saveCommunity, type CommunityStatus } from "./api";

export const route = { path: "/community", navLabel: "Community" };

const card: CSSProperties = {
  border: "1px solid var(--wb-border)",
  borderRadius: 8,
  padding: 16,
  background: "var(--wb-surface)",
  marginBottom: 16,
};
const muted: CSSProperties = { color: "var(--wb-text-muted)", fontSize: "0.9em" };
const field: CSSProperties = { display: "block", margin: "12px 0" };

export default function CommunityPage() {
  const { user } = useAuth();
  const [status, setStatus] = useState<CommunityStatus | null>(null);
  const [dbName, setDbName] = useState("");
  const [siteUrl, setSiteUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function apply(next: CommunityStatus) {
    setStatus(next);
    setDbName(next.db_name);
    setSiteUrl(next.site_url);
  }

  useEffect(() => {
    if (user?.level !== "owner") return;
    getCommunity().then(apply).catch((e: Error) => setError(e.message));
  }, [user?.level]);

  if (user?.level !== "owner") return <main style={{ padding: 24 }}>Nur für den Owner.</main>;

  async function save() {
    setBusy(true);
    setError(null);
    try {
      apply(await saveCommunity(dbName, siteUrl));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main style={{ padding: 24, maxWidth: 760 }}>
      <h1>Community-Seite</h1>
      <p style={muted}>
        Anbindung an die Datenbank der Community-Seite – Grundlage für Verknüpfen, News, Events und Tickets in
        Discord. Ohne Anbindung läuft der Bot ganz normal weiter.
      </p>

      {error && <p style={{ ...card, borderColor: "var(--wb-danger)" }}>{error}</p>}

      {status && (
        <section style={card}>
          <h2 style={{ marginTop: 0 }}>Zustand</h2>
          <p>
            {status.connected ? "✅" : status.enabled ? "❌" : "⚪"} {status.message}
          </p>
          {status.connected && (
            <ul style={{ margin: 0 }}>
              <li>Verknüpfte Mitglieder: {status.linked ?? "–"}</li>
              <li>
                Offene Aufträge der Seite: {status.pending ?? "–"}
                {status.failed ? ` · ⚠️ endgültig fehlgeschlagen: ${status.failed}` : ""}
              </li>
              <li>Zuständig für: {status.handlers.join(", ") || "–"}</li>
            </ul>
          )}
        </section>
      )}

      <section style={card}>
        <h2 style={{ marginTop: 0 }}>Einstellungen</h2>
        <label style={field}>
          Datenbank der Seite
          <br />
          <input value={dbName} onChange={(e) => setDbName(e.target.value)} placeholder="php" />
          <span style={{ ...muted, marginLeft: 8 }}>
            auf {status?.db_host ?? "dem Datenbank-Server des Bots"}, mit demselben Benutzer (AMP → Datenbank)
          </span>
        </label>
        <label style={field}>
          Adresse der Seite (für Links in Discord)
          <br />
          <input
            style={{ width: "100%", maxWidth: 420 }}
            value={siteUrl}
            onChange={(e) => setSiteUrl(e.target.value)}
            placeholder="https://community.example.com"
          />
        </label>
        <button disabled={busy} onClick={() => void save()}>
          {busy ? "Prüfe…" : "Speichern und verbinden"}
        </button>
        <p style={muted}>
          Datenbank leer lassen = Anbindung aus. Nach dem Verbinden auf der Seite in <code>config.local.php</code>{" "}
          <code>'discord_enabled' =&gt; true</code> setzen.
        </p>
      </section>
    </main>
  );
}
