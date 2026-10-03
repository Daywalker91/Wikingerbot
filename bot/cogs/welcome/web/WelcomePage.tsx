import { useEffect, useState, type CSSProperties } from "react";

import { useAuth } from "@/auth/useAuth";

import { getWelcome, saveWelcome, type WelcomeConfig, type WelcomeData } from "./api";

export const route = { path: "/welcome", navLabel: "Begrüßung" };

const card: CSSProperties = {
  border: "1px solid var(--wb-border)",
  borderRadius: 8,
  padding: 16,
  background: "var(--wb-surface)",
  marginBottom: 16,
};
const muted: CSSProperties = { color: "var(--wb-text-muted)", fontSize: "0.9em" };
const textarea: CSSProperties = {
  width: "100%",
  minHeight: 90,
  background: "var(--wb-bg)",
  color: "var(--wb-text)",
  border: "1px solid var(--wb-border)",
  borderRadius: 4,
  padding: 8,
  fontFamily: "inherit",
};
const preview: CSSProperties = {
  whiteSpace: "pre-wrap",
  borderLeft: "3px solid var(--wb-accent)",
  padding: "6px 10px",
  margin: "8px 0 0",
  background: "rgba(0,0,0,0.2)",
};

function render(text: string, data: WelcomeData, name: string): string {
  const channelName = (id: string) => data.text_channels.find((c) => c.id === id)?.name ?? "unbekannter-kanal";
  return text
    .split("\\n") // "\n" als zwei Zeichen = Zeilenumbruch, wie im Bot
    .join("\n")
    .replace(/<#(\d+)>/g, (_, id: string) => `#${channelName(id)}`) // Kanal-Erwaehnung wie in Discord
    .split("{user}")
    .join(`@${name}`)
    .split("{name}")
    .join(name)
    .split("{server}")
    .join(data.server_name || "Server")
    .split("{count}")
    .join(String(data.member_count || 42));
}

function ChannelSelect({
  value,
  channels,
  empty,
  onChange,
}: {
  value: string | null;
  channels: WelcomeData["text_channels"];
  empty: string;
  onChange: (id: string | null) => void;
}) {
  return (
    <select value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">{empty}</option>
      {channels.map((c) => (
        <option key={c.id} value={c.id}>
          #{c.name}
        </option>
      ))}
    </select>
  );
}

export default function WelcomePage() {
  const { user } = useAuth();
  const [data, setData] = useState<WelcomeData | null>(null);
  const [config, setConfig] = useState<WelcomeConfig | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const isAdmin = user?.level === "admin" || user?.level === "owner";

  useEffect(() => {
    if (!isAdmin) return;
    getWelcome()
      .then((loaded) => {
        setData(loaded);
        setConfig(loaded.config);
      })
      .catch((e: Error) => setNote(e.message));
  }, [isAdmin]);

  if (!isAdmin) return <main style={{ padding: 24 }}>Nur für Admins.</main>;
  if (!data || !config) return <main style={{ padding: 24 }}>{note ?? "Lädt…"}</main>;

  const set = (change: Partial<WelcomeConfig>) => setConfig({ ...config, ...change });
  const sample = "Ragnar";

  async function save() {
    setNote(null);
    try {
      await saveWelcome(config!);
      setNote("Gespeichert.");
    } catch (error) {
      setNote((error as Error).message);
    }
  }

  return (
    <main style={{ padding: 24, maxWidth: 820 }}>
      <h1>Begrüßung</h1>
      <p style={muted}>
        Platzhalter: <code>{"{user}"}</code> Erwähnung, <code>{"{name}"}</code> Anzeigename,{" "}
        <code>{"{server}"}</code> Servername, <code>{"{count}"}</code> Mitgliederzahl. Gepingt wird nur das neue
        Mitglied. Die Vorschau zeigt „{sample}“ als Beispiel. Mit Discords Mitgliedschaftsprüfung wird erst begrüßt, wenn
        die Regeln akzeptiert sind.
      </p>

      <section style={card}>
        <h2 style={{ marginTop: 0 }}>Begrüßung im Kanal</h2>
        <ChannelSelect
          value={config.channel_id}
          channels={data.text_channels}
          empty="– aus –"
          onChange={(id) => set({ channel_id: id })}
        />
        <textarea style={{ ...textarea, marginTop: 8 }} value={config.message} onChange={(e) => set({ message: e.target.value })} />
        {config.channel_id && <p style={preview}>{render(config.message, data, sample)}</p>}
      </section>

      <section style={card}>
        <h2 style={{ marginTop: 0 }}>Willkommens-DM</h2>
        <p style={muted}>Leer lassen = keine DM. Gut für Regeln und den Link zur Seite.</p>
        <textarea style={textarea} value={config.dm_message} onChange={(e) => set({ dm_message: e.target.value })} />
        {config.dm_message && <p style={preview}>{render(config.dm_message, data, sample)}</p>}
      </section>

      <section style={card}>
        <h2 style={{ marginTop: 0 }}>Abschied</h2>
        <label>
          <input
            type="checkbox"
            checked={config.goodbye_enabled}
            onChange={(e) => set({ goodbye_enabled: e.target.checked })}
          />{" "}
          Melden, wenn jemand den Server verlässt
        </label>
        {config.goodbye_enabled && (
          <>
            <div style={{ marginTop: 8 }}>
              <ChannelSelect
                value={config.goodbye_channel_id}
                channels={data.text_channels}
                empty="– wie Begrüßung –"
                onChange={(id) => set({ goodbye_channel_id: id })}
              />
            </div>
            <textarea
              style={{ ...textarea, marginTop: 8 }}
              value={config.goodbye_message}
              onChange={(e) => set({ goodbye_message: e.target.value })}
            />
            <p style={preview}>{render(config.goodbye_message, data, sample)}</p>
          </>
        )}
      </section>

      <button onClick={() => void save()}>Speichern</button>
      {note && <span style={{ ...muted, marginLeft: 12 }}>{note}</span>}
    </main>
  );
}
