import { useCallback, useEffect, useState, type CSSProperties } from "react";

import { useAuth } from "@/auth/useAuth";

import { getEvents, saveEvents, syncEvent, type EventsData, type EventsSettings } from "./api";

export const route = { path: "/events", navLabel: "Events" };

const card: CSSProperties = {
  border: "1px solid var(--wb-border)",
  borderRadius: 8,
  padding: 16,
  background: "var(--wb-surface)",
  marginBottom: 16,
};
const muted: CSSProperties = { color: "var(--wb-text-muted)", fontSize: "0.9em" };
const row: CSSProperties = { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", margin: "8px 0" };

function when(iso: string): string {
  return new Date(iso).toLocaleString("de-DE", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export default function EventsPage() {
  const { user } = useAuth();
  const isAdmin = user?.level === "admin" || user?.level === "owner";
  const [data, setData] = useState<EventsData | null>(null);
  const [settings, setSettings] = useState<EventsSettings>({ channel_id: null, ping_role_id: null, native: true });
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    const loaded = await getEvents();
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
    <main style={{ padding: 24, maxWidth: 860 }}>
      <h1>Events</h1>
      <p style={muted}>
        Events der Community-Seite mit Haken „In Discord ankündigen“ erscheinen im Event-Kanal mit den Knöpfen Dabei /
        Vielleicht / Nicht dabei – die Zusagen gelten auf der Seite (nur mit verknüpftem Konto). Änderungen und Absagen
        werden nachgezogen.
      </p>
      {!data.community_enabled && (
        <p style={{ ...card, borderColor: "var(--wb-border-strong)" }}>Die Community-Seite ist nicht angebunden (Tab Community).</p>
      )}
      {note && <p style={{ ...card, padding: "8px 12px" }}>{note}</p>}

      <section style={card}>
        <h2 style={{ marginTop: 0 }}>Einstellungen</h2>
        <div style={row}>
          Event-Kanal:
          <select value={settings.channel_id ?? ""} onChange={(e) => setSettings({ ...settings, channel_id: e.target.value || null })}>
            <option value="">– aus –</option>
            {data.text_channels.map((c) => (
              <option key={c.id} value={c.id}>
                #{c.name}
              </option>
            ))}
          </select>
        </div>
        <div style={row}>
          Rolle anpingen:
          <select value={settings.ping_role_id ?? ""} onChange={(e) => setSettings({ ...settings, ping_role_id: e.target.value || null })}>
            <option value="">– niemand –</option>
            {data.roles.map((r) => (
              <option key={r.id} value={r.id}>
                @{r.name}
              </option>
            ))}
          </select>
          <span style={muted}>nur beim ersten Posten</span>
        </div>
        <div style={row}>
          <label>
            <input type="checkbox" checked={settings.native} onChange={(e) => setSettings({ ...settings, native: e.target.checked })} />{" "}
            Zusätzlich als Discord-Event anlegen (Event-Bereich des Servers)
          </label>
        </div>
        {settings.native && !data.can_manage_events && (
          <p style={{ ...muted, color: "var(--wb-accent-strong)" }}>
            Dafür braucht die Bot-Rolle in Discord das Recht „Events verwalten“ – sonst wird nur die Nachricht gepostet.
          </p>
        )}
        <button onClick={() => void act(() => saveEvents(settings))}>Speichern</button>
      </section>

      {data.community_enabled && (
        <section style={card}>
          <h2 style={{ marginTop: 0 }}>Nächste Events</h2>
          {data.error && <p style={muted}>{data.error}</p>}
          {data.upcoming.length === 0 && !data.error && <p style={muted}>Keine kommenden Events.</p>}
          {data.upcoming.map((ev) => (
            <div key={ev.id} style={{ ...row, borderBottom: "1px solid var(--wb-border)", paddingBottom: 6 }}>
              <span style={{ ...muted, minWidth: 120 }}>{when(ev.starts_at)}</span>
              <span style={{ flex: 1 }}>
                {ev.cancelled && "❌ "}
                {ev.link ? (
                  <a href={ev.link} target="_blank" rel="noreferrer">
                    {ev.title}
                  </a>
                ) : (
                  ev.title
                )}
              </span>
              <span style={muted}>{!ev.announce ? "nicht ankündigen" : ev.posted ? "✅ in Discord" : "noch nicht gepostet"}</span>
              {ev.announce && (
                <button
                  disabled={!settings.channel_id}
                  title={settings.channel_id ? "" : "Erst einen Event-Kanal speichern"}
                  onClick={() => void act(() => syncEvent(ev.id), (r) => (r as { done: string[] }).done.join(", "))}
                >
                  {ev.posted ? "Aktualisieren" : "Jetzt posten"}
                </button>
              )}
            </div>
          ))}
        </section>
      )}
    </main>
  );
}
