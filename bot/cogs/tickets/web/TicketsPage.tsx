import { useCallback, useEffect, useState, type CSSProperties } from "react";

import { useAuth } from "@/auth/useAuth";

import { getTickets, saveTickets, syncTicket, type TicketSettings, type TicketsData } from "./api";

export const route = { path: "/tickets", navLabel: "Tickets" };

const card: CSSProperties = {
  border: "1px solid var(--wb-border)",
  borderRadius: 8,
  padding: 16,
  background: "var(--wb-surface)",
  marginBottom: 16,
};
const muted: CSSProperties = { color: "var(--wb-text-muted)", fontSize: "0.9em" };
const row: CSSProperties = { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", margin: "8px 0" };

export default function TicketsPage() {
  const { user } = useAuth();
  const isAdmin = user?.level === "admin" || user?.level === "owner";
  const [data, setData] = useState<TicketsData | null>(null);
  const [settings, setSettings] = useState<TicketSettings>({ channel_id: null, ping_role_id: null, dm: true });
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    const loaded = await getTickets();
    setData(loaded);
    setSettings(loaded.settings);
  }, []);

  useEffect(() => {
    if (isAdmin) load().catch((e: Error) => setNote(e.message));
  }, [isAdmin, load]);

  if (!isAdmin) return <main style={{ padding: 24 }}>Nur für Admins.</main>;
  if (!data) return <main style={{ padding: 24 }}>{note ?? "Lädt…"}</main>;

  async function act(action: () => Promise<unknown>, success?: (r: unknown) => string) {
    setNote(null);
    try {
      const result = await action();
      setNote(success ? success(result) : "Gespeichert.");
      await load();
    } catch (error) {
      setNote((error as Error).message);
    }
  }

  return (
    <main style={{ padding: 24, maxWidth: 900 }}>
      <h1>Tickets</h1>
      <p style={muted}>
        Jedes Ticket der Seite bekommt einen Thread im Staff-Kanal – voll gespiegelt: was auf der Seite steht, erscheint im
        Thread; was der Support im Thread schreibt, landet als Antwort auf der Seite („!intern …“ = interne Notiz). Das
        Mitglied bekommt Antworten per DM und kann direkt daraus antworten. Wer schreibt, muss mit der Seite verknüpft sein;
        bearbeiten darf, wer auf der Seite das Recht „Tickets verwalten“ hat. In einem Forum bekommt jeder Beitrag Tags für
        Status und Kategorie – zum Anlegen fehlender Tags braucht der Bot dort „Kanäle verwalten“.
      </p>
      {!data.community_enabled && (
        <p style={{ ...card, borderColor: "var(--wb-border-strong)" }}>Die Community-Seite ist nicht angebunden (Tab Community).</p>
      )}
      {note && <p style={{ ...card, padding: "8px 12px" }}>{note}</p>}

      <section style={card}>
        <h2 style={{ marginTop: 0 }}>Einstellungen</h2>
        <div style={row}>
          Staff-Kanal:
          <select value={settings.channel_id ?? ""} onChange={(e) => setSettings({ ...settings, channel_id: e.target.value || null })}>
            <option value="">– keiner (nur DMs) –</option>
            {data.channels.map((c) => (
              <option key={c.id} value={c.id}>
                {c.forum ? "🗂️ " : "#"}
                {c.name}
                {c.forum ? " (Forum)" : ""}
              </option>
            ))}
          </select>
          <span style={muted}>am besten ein Kanal nur für Support</span>
        </div>
        <div style={row}>
          Bei neuen Tickets anpingen:
          <select value={settings.ping_role_id ?? ""} onChange={(e) => setSettings({ ...settings, ping_role_id: e.target.value || null })}>
            <option value="">– niemand –</option>
            {data.roles.map((r) => (
              <option key={r.id} value={r.id}>
                @{r.name}
              </option>
            ))}
          </select>
        </div>
        <div style={row}>
          <label>
            <input type="checkbox" checked={settings.dm} onChange={(e) => setSettings({ ...settings, dm: e.target.checked })} /> Mitglieder per
            DM über Antworten und das Schließen informieren
          </label>
        </div>
        <button onClick={() => void act(() => saveTickets(settings))}>Speichern</button>
      </section>

      {data.community_enabled && (
        <section style={card}>
          <h2 style={{ marginTop: 0 }}>Offene Tickets</h2>
          {data.error && <p style={muted}>{data.error}</p>}
          {data.open.length === 0 && !data.error && <p style={muted}>Keine offenen Tickets.</p>}
          {data.open.map((t) => (
            <div key={t.id} style={{ ...row, borderBottom: "1px solid var(--wb-border)", paddingBottom: 6 }}>
              <span style={{ flex: 1 }}>
                #{t.id}{" "}
                {t.link ? (
                  <a href={t.link} target="_blank" rel="noreferrer">
                    {t.subject}
                  </a>
                ) : (
                  t.subject
                )}{" "}
                <span style={muted}>
                  · {t.author} · {t.status}
                  {t.assigned ? ` · ${t.assigned}` : ""}
                </span>
              </span>
              <span style={muted}>{t.has_thread ? "✅ Thread" : "kein Thread"}</span>
              <button
                disabled={!settings.channel_id}
                onClick={() => void act(() => syncTicket(t.id), (r) => (r as { done: string[] }).done.join(", "))}
              >
                {t.has_thread ? "Abgleichen" : "Thread anlegen"}
              </button>
            </div>
          ))}
        </section>
      )}
    </main>
  );
}
