import { useCallback, useEffect, useState, type CSSProperties } from "react";

import { useAuth } from "@/auth/useAuth";

import {
  addNotice,
  cancelNotice,
  getAmpPreview,
  getNotices,
  getServerNews,
  saveServerNews,
  testIngame,
  type AmpPreview,
  type Notice,
  type ServerNewsData,
  type ServerNewsSettings,
} from "./api";

export const route = { path: "/servernews", navLabel: "Server-News" };

const card: CSSProperties = {
  border: "1px solid var(--wb-border)",
  borderRadius: 8,
  padding: 16,
  background: "var(--wb-surface)",
  marginBottom: 16,
};
const muted: CSSProperties = { color: "var(--wb-text-muted)", fontSize: "0.9em" };
const row: CSSProperties = { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", margin: "8px 0" };
const KIND: Record<string, string> = { restart: "🔄 Neustart", update: "⬆️ Update", stop: "⏹️ Stopp", maintenance: "🔧 Wartung" };

export default function ServerNewsPage() {
  const { user } = useAuth();
  const isAdmin = user?.level === "admin" || user?.level === "owner";
  const [data, setData] = useState<ServerNewsData | null>(null);
  const [settings, setSettings] = useState<ServerNewsSettings | null>(null);
  const [ingame, setIngame] = useState<Record<string, string>>({});
  const [notices, setNotices] = useState<Notice[]>([]);
  const [preview, setPreview] = useState<AmpPreview | null>(null);
  const [form, setForm] = useState({ server_id: "", kind: "restart", start: "15", duration: "", reason: "" });
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    const loaded = await getServerNews();
    setData(loaded);
    setSettings(loaded.settings);
    setIngame(Object.fromEntries(loaded.servers.map((s) => [String(s.id), s.ingame])));
    setNotices(await getNotices().catch(() => []));
  }, []);

  useEffect(() => {
    if (isAdmin) load().catch((e: Error) => setNote(e.message));
  }, [isAdmin, load]);

  if (!isAdmin) return <main style={{ padding: 24 }}>Nur für Admins.</main>;
  if (!data || !settings) return <main style={{ padding: 24 }}>{note ?? "Lädt…"}</main>;

  async function act(action: () => Promise<{ message: string }>) {
    setNote(null);
    try {
      setNote((await action()).message);
      await load();
    } catch (error) {
      setNote((error as Error).message);
    }
  }

  return (
    <main style={{ padding: 24, maxWidth: 960 }}>
      <h1>Server-News</h1>
      <p style={muted}>
        Neustarts, Wartungen und Ausfälle der Gameserver in Discord ankündigen. Von Hand mit <code>/wartung</code> oder unten; auf Wunsch
        auch die geplanten Neustarts aus dem AMP-Zeitplan. Nur die erste Meldung pingt, danach Erinnerungen ohne Ping, zum Schluss „läuft
        wieder“.
      </p>
      {!data.cog_loaded && <p style={card}>Der servernews-Cog ist nicht geladen.</p>}
      {note && <p style={{ ...card, padding: "8px 12px" }}>{note}</p>}

      <section style={card}>
        <h2 style={{ marginTop: 0 }}>Einstellungen</h2>
        <div style={row}>
          Kanal:
          <select value={settings.channel_id ?? ""} onChange={(e) => setSettings({ ...settings, channel_id: e.target.value || null })}>
            <option value="">– aus –</option>
            {data.text_channels.map((c) => (
              <option key={c.id} value={c.id}>
                #{c.name}
              </option>
            ))}
          </select>
          Ping:
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
          Vorher ankündigen (Minuten):
          <input value={settings.leads} onChange={(e) => setSettings({ ...settings, leads: e.target.value })} style={{ width: 140 }} />
          <span style={muted}>z.B. „60, 15, 5“ – die erste pingt, die anderen erinnern</span>
        </div>
        <div style={row}>
          <label>
            <input type="checkbox" checked={settings.outages} onChange={(e) => setSettings({ ...settings, outages: e.target.checked })} /> Nicht
            angekündigte Ausfälle melden (ohne Ping)
          </label>
        </div>
        <div style={row}>
          <label>
            <input
              type="checkbox"
              checked={settings.amp_schedule}
              onChange={(e) => setSettings({ ...settings, amp_schedule: e.target.checked })}
            />{" "}
            Geplante Neustarts/Updates aus dem AMP-Zeitplan ankündigen
          </label>
          <span style={muted}>erst einschalten, wenn die Vorschau unten die richtigen Zeiten zeigt</span>
        </div>

        <h3 style={{ margin: "16px 0 4px" }}>Hinweis im Spiel</h3>
        <p style={muted}>
          Zusätzlich eine Nachricht an alle Spieler über die Server-Konsole. Jedes Spiel macht das anders – <code>{"{text}"}</code> steht für
          die Nachricht, leer = nur Discord. Mit „Testen“ schickt der Bot eine Testnachricht – im Spiel nachsehen, ob sie ankommt.
        </p>
        {data.servers.map((s) => (
          <div key={s.id} style={row}>
            <span style={{ minWidth: 160 }}>{s.name}</span>
            <input
              value={ingame[String(s.id)] ?? ""}
              onChange={(e) => setIngame({ ...ingame, [String(s.id)]: e.target.value })}
              placeholder={s.suggestion || "z.B. say {text}"}
              style={{ minWidth: 220 }}
            />
            {s.suggestion && !ingame[String(s.id)] && (
              <button onClick={() => setIngame({ ...ingame, [String(s.id)]: s.suggestion })}>Vorschlag übernehmen</button>
            )}
            <button disabled={!ingame[String(s.id)]} onClick={() => void act(() => testIngame(s.id, ingame[String(s.id)]))}>
              Testen
            </button>
          </div>
        ))}
        <button onClick={() => void act(() => saveServerNews(settings, ingame))}>Speichern</button>
      </section>

      <section style={card}>
        <h2 style={{ marginTop: 0 }}>Angekündigt</h2>
        {notices.length === 0 && <p style={muted}>Nichts angekündigt.</p>}
        {notices.map((n) => (
          <div key={n.id} style={{ ...row, borderBottom: "1px solid var(--wb-border)", paddingBottom: 6 }}>
            <span style={{ flex: 1 }}>
              <strong>{n.server}</strong> · {KIND[n.kind] ?? n.kind} · {new Date(n.at * 1000).toLocaleString("de-DE")}
              {n.origin === "amp" ? " · aus AMP" : ""}
              {n.status === "running" ? " · läuft gerade" : ""}
              {n.reason ? ` · ${n.reason}` : ""}
            </span>
            <button onClick={() => void act(() => cancelNotice(n.id))}>Absagen</button>
          </div>
        ))}
        <h3 style={{ margin: "16px 0 4px" }}>Neu ankündigen</h3>
        <div style={row}>
          <select value={form.server_id} onChange={(e) => setForm({ ...form, server_id: e.target.value })}>
            <option value="">– Server –</option>
            {data.servers.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            <option value="restart">Neustart (Bot startet neu)</option>
            <option value="maintenance">Wartung (Bot stoppt)</option>
          </select>
          Start:
          <input value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} style={{ width: 70 }} title="Minuten ab jetzt oder Uhrzeit" />
          {form.kind === "maintenance" && (
            <>
              Dauer:
              <input value={form.duration} onChange={(e) => setForm({ ...form, duration: e.target.value.replace(/\D/g, "") })} style={{ width: 60 }} placeholder="Min." />
            </>
          )}
          <input value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} placeholder="Grund (optional)" maxLength={200} />
          <button
            disabled={!form.server_id || !form.start}
            onClick={() =>
              void act(() =>
                addNotice({
                  server_id: Number(form.server_id),
                  kind: form.kind,
                  start: form.start,
                  duration_min: form.duration ? Number(form.duration) : null,
                  reason: form.reason || null,
                }),
              )
            }
          >
            Ankündigen
          </button>
        </div>
        <p style={muted}>Start: Minuten ab jetzt (z.B. 15) oder Uhrzeit (z.B. 20:00).</p>
      </section>

      <section style={card}>
        <h2 style={{ marginTop: 0 }}>Vorschau: AMP-Zeitplan</h2>
        <p style={muted}>
          Was der Bot aus den Zeitplänen in AMP liest (Zeit-Trigger mit Neustart, Update oder Stopp). Stimmen die Zeiten mit AMP überein,
          kannst du oben „aus dem AMP-Zeitplan ankündigen“ einschalten.
        </p>
        <button onClick={() => getAmpPreview().then(setPreview).catch((e: Error) => setNote(e.message))}>Zeitpläne lesen</button>
        {preview && (
          <div style={{ marginTop: 8 }}>
            <p style={muted}>Jetzt: {preview.now}</p>
            {preview.servers.map((s) => (
              <div key={s.server} style={{ margin: "6px 0" }}>
                <strong>{s.server}</strong>
                {s.error ? (
                  <span style={muted}> – {s.error}</span>
                ) : s.runs.length === 0 ? (
                  <span style={muted}> – keine geplanten Neustarts</span>
                ) : (
                  s.runs.map((r, i) => (
                    <div key={i} style={muted}>
                      {KIND[r.kind] ?? r.kind} · nächster Lauf {r.at}
                      {r.label ? ` · ${r.label}` : ""}
                    </div>
                  ))
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
