import { useCallback, useEffect, useState, type CSSProperties } from "react";

import { useAuth } from "@/auth/useAuth";
import CategoryRoles from "@/components/CategoryRoles";

import { getNews, saveNews, syncNews, type NewsData, type NewsSettings } from "./api";

export const route = { path: "/news", navLabel: "News" };

const card: CSSProperties = {
  border: "1px solid var(--wb-border)",
  borderRadius: 8,
  padding: 16,
  background: "var(--wb-surface)",
  marginBottom: 16,
};
const muted: CSSProperties = { color: "var(--wb-text-muted)", fontSize: "0.9em" };
const row: CSSProperties = { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", margin: "8px 0" };

export default function NewsPage() {
  const { user } = useAuth();
  const isAdmin = user?.level === "admin" || user?.level === "owner";
  const [data, setData] = useState<NewsData | null>(null);
  const [settings, setSettings] = useState<NewsSettings>({ channel_id: null, ping_role_id: null });
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    const loaded = await getNews();
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
      <h1>News</h1>
      <p style={muted}>
        Veröffentlichte News der Community-Seite mit Haken „In Discord ankündigen“ landen als Nachricht im News-Kanal.
        Bearbeiten auf der Seite aktualisiert sie, Löschen oder Zurückziehen entfernt sie wieder. In einem Ankündigungskanal
        veröffentlicht der Bot sie gleich mit.
      </p>
      {!data.community_enabled && (
        <p style={{ ...card, borderColor: "var(--wb-border-strong)" }}>Die Community-Seite ist nicht angebunden (Tab Community).</p>
      )}
      {note && <p style={{ ...card, padding: "8px 12px" }}>{note}</p>}

      <section style={card}>
        <h2 style={{ marginTop: 0 }}>Einstellungen</h2>
        <div style={row}>
          News-Kanal:
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
          <span style={muted}>nur beim ersten Posten, nicht bei Änderungen</span>
        </div>
        <button onClick={() => void act(() => saveNews(settings))}>Speichern</button>
      </section>

      {data.community_enabled && (
        <CategoryRoles
          apiBase="/news"
          categories={data.categories}
          error={data.categories_error}
          roles={data.roles}
          onSaved={(message) => {
            setNote(message);
            void load();
          }}
        />
      )}

      {data.community_enabled && (
        <section style={card}>
          <h2 style={{ marginTop: 0 }}>Neueste News</h2>
          {data.error && <p style={muted}>{data.error}</p>}
          {data.recent.length === 0 && !data.error && <p style={muted}>Noch keine News auf der Seite.</p>}
          {data.recent.map((n) => (
            <div key={n.id} style={{ ...row, borderBottom: "1px solid var(--wb-border)", paddingBottom: 6 }}>
              <span style={{ flex: 1 }}>
                {n.link ? (
                  <a href={n.link} target="_blank" rel="noreferrer">
                    {n.title}
                  </a>
                ) : (
                  n.title
                )}
              </span>
              <span style={muted}>
                {!n.published ? "Entwurf" : !n.announce ? "nicht ankündigen" : n.posted ? "✅ in Discord" : "noch nicht gepostet"}
              </span>
              {n.published && n.announce && (
                <button
                  disabled={!settings.channel_id}
                  title={settings.channel_id ? "" : "Erst einen News-Kanal speichern"}
                  onClick={() => void act(() => syncNews(n.id), (r) => (r as { done: string[] }).done.join(", "))}
                >
                  {n.posted ? "Aktualisieren" : "Jetzt posten"}
                </button>
              )}
            </div>
          ))}
        </section>
      )}
    </main>
  );
}
