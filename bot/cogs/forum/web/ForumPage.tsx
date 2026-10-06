import { useCallback, useEffect, useState, type CSSProperties } from "react";

import { useAuth } from "@/auth/useAuth";

import { announceThread, getForum, saveForum, type ForumData, type ForumSettings } from "./api";

export const route = { path: "/forum", navLabel: "Forum" };

const card: CSSProperties = {
  border: "1px solid var(--wb-border)",
  borderRadius: 8,
  padding: 16,
  background: "var(--wb-surface)",
  marginBottom: 16,
};
const muted: CSSProperties = { color: "var(--wb-text-muted)", fontSize: "0.9em" };
const row: CSSProperties = { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", margin: "8px 0" };

export default function ForumPage() {
  const { user } = useAuth();
  const isAdmin = user?.level === "admin" || user?.level === "owner";
  const [data, setData] = useState<ForumData | null>(null);
  const [settings, setSettings] = useState<ForumSettings>({ channel_id: null, ping_role_id: null });
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    const loaded = await getForum();
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
      <h1>Forum</h1>
      <p style={muted}>
        Neue Themen im Forum der Community-Seite werden im gewählten Kanal kurz angekündigt – Titel, Verfasser, Kategorie, der
        Anfang des Texts und ein Knopf „Hier lesen“. Antworten nicht. Nur Kategorien, die jeder lesen darf; interne Bereiche
        erscheinen nie in Discord.
      </p>
      {!data.community_enabled && (
        <p style={{ ...card, borderColor: "var(--wb-border-strong)" }}>Die Community-Seite ist nicht angebunden (Tab Community).</p>
      )}
      {!data.cog_loaded && <p style={card}>Der Forum-Cog ist nicht geladen.</p>}
      {note && <p style={{ ...card, padding: "8px 12px" }}>{note}</p>}

      <section style={card}>
        <h2 style={{ marginTop: 0 }}>Einstellungen</h2>
        <div style={row}>
          Kanal für Ankündigungen:
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
        </div>
        <button onClick={() => void act(() => saveForum(settings))}>Speichern</button>
      </section>

      {data.community_enabled && (
        <section style={card}>
          <h2 style={{ marginTop: 0 }}>Neueste Themen</h2>
          {data.error && <p style={muted}>{data.error}</p>}
          {data.recent.length === 0 && !data.error && <p style={muted}>Noch keine öffentlichen Themen.</p>}
          {data.recent.map((t) => (
            <div key={t.id} style={{ ...row, borderBottom: "1px solid var(--wb-border)", paddingBottom: 6 }}>
              <span style={{ flex: 1 }}>
                {t.link ? (
                  <a href={t.link} target="_blank" rel="noreferrer">
                    {t.title}
                  </a>
                ) : (
                  t.title
                )}{" "}
                <span style={muted}>
                  · {t.category}
                  {t.author ? ` · ${t.author}` : ""}
                </span>
              </span>
              <span style={muted}>{t.posted ? "✅ angekündigt" : "noch nicht angekündigt"}</span>
              {!t.posted && (
                <button
                  disabled={!settings.channel_id}
                  title={settings.channel_id ? "" : "Erst einen Kanal speichern"}
                  onClick={() => void act(() => announceThread(t.id), (r) => (r as { done: string[] }).done.join(", "))}
                >
                  Jetzt ankündigen
                </button>
              )}
            </div>
          ))}
        </section>
      )}
    </main>
  );
}
