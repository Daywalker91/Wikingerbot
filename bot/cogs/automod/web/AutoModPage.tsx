import { useEffect, useState, type CSSProperties, type ReactNode } from "react";

import { useAuth } from "@/auth/useAuth";

import { getAutoMod, saveAutoMod, type AutoModConfig, type AutoModData, type AutoModRules } from "./api";

export const route = { path: "/automod", navLabel: "AutoMod" };

const card: CSSProperties = {
  border: "1px solid var(--wb-border)",
  borderRadius: 8,
  padding: 16,
  background: "var(--wb-surface)",
  marginBottom: 16,
};
const muted: CSSProperties = { color: "var(--wb-text-muted)", fontSize: "0.9em" };
const row: CSSProperties = { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", margin: "8px 0" };
const num: CSSProperties = { width: 70 };

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={card}>
      <h2 style={{ marginTop: 0 }}>{title}</h2>
      {children}
    </section>
  );
}

function Num({ value, min, max, onChange }: { value: number; min: number; max: number; onChange: (v: number) => void }) {
  return (
    <input
      type="number"
      style={num}
      min={min}
      max={max}
      value={value}
      onChange={(e) => onChange(Math.max(min, Math.min(max, Number(e.target.value) || min)))}
    />
  );
}

function Check({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode }) {
  return (
    <label>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} /> {children}
    </label>
  );
}

function MultiSelect({
  items,
  selected,
  prefix,
  onChange,
}: {
  items: { id: string; name: string }[];
  selected: string[];
  prefix: string;
  onChange: (ids: string[]) => void;
}) {
  return (
    <select
      multiple
      size={Math.min(8, Math.max(3, items.length))}
      value={selected}
      onChange={(e) => onChange(Array.from(e.target.selectedOptions, (o) => o.value))}
      style={{ minWidth: 220 }}
    >
      {items.map((item) => (
        <option key={item.id} value={item.id}>
          {prefix}
          {item.name}
        </option>
      ))}
    </select>
  );
}

export default function AutoModPage() {
  const { user } = useAuth();
  const isAdmin = user?.level === "admin" || user?.level === "owner";
  const [data, setData] = useState<AutoModData | null>(null);
  const [config, setConfig] = useState<AutoModConfig | null>(null);
  const [allowText, setAllowText] = useState("");
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    if (!isAdmin) return;
    getAutoMod()
      .then((loaded) => {
        setData(loaded);
        setConfig(loaded.config);
        setAllowText(loaded.config.rules.links.allow.join("\n"));
      })
      .catch((e: Error) => setNote(e.message));
  }, [isAdmin]);

  if (!isAdmin) return <main style={{ padding: 24 }}>Nur für Admins.</main>;
  if (!data || !config) return <main style={{ padding: 24 }}>{note ?? "Lädt…"}</main>;

  const rules = config.rules;
  const setRules = (change: Partial<AutoModRules>) => setConfig({ ...config, rules: { ...rules, ...change } });

  async function save() {
    setNote(null);
    const allow = allowText
      .split(/[\s,]+/)
      .map((d) => d.trim())
      .filter(Boolean);
    try {
      await saveAutoMod({ ...config!, rules: { ...rules, links: { ...rules.links, allow } } });
      setNote("Gespeichert – gilt sofort.");
    } catch (error) {
      setNote((error as Error).message);
    }
  }

  return (
    <main style={{ padding: 24, maxWidth: 900 }}>
      <h1>AutoMod</h1>
      {!data.moderation_loaded && (
        <p style={{ ...card, borderColor: "var(--wb-border-strong)" }}>
          Der Moderations-Cog ist nicht geladen – Warn-Punkte werden dann nicht vergeben, AutoMod löscht und meldet nur.
        </p>
      )}

      <Card title="Meldungen">
        <div style={row}>
          Alarmkanal für alle AutoMod-Meldungen:
          <select
            value={config.alert_channel_id ?? ""}
            onChange={(e) => setConfig({ ...config, alert_channel_id: e.target.value || null })}
          >
            <option value="">– keiner –</option>
            {data.text_channels.map((c) => (
              <option key={c.id} value={c.id}>
                #{c.name}
              </option>
            ))}
          </select>
        </div>
      </Card>

      <Card title="Discords eigener AutoMod">
        <p style={muted}>
          Die Regeln selbst stellst du in Discord ein (Servereinstellungen → Sicherheit → AutoMod). Blockiert Discord
          eine Nachricht, vergibt der Bot hier Warn-Punkte – mit der Eskalation aus dem Moderations-Tab.
        </p>
        <Check checked={config.discord.enabled} onChange={(v) => setConfig({ ...config, discord: { ...config.discord, enabled: v } })}>
          Warn-Punkte vergeben
        </Check>
        {config.discord.enabled &&
          Object.entries(data.trigger_labels).map(([key, label]) => (
            <div key={key} style={row}>
              <span style={{ minWidth: 200 }}>{label}</span>
              <Num
                value={config.discord.points[key] ?? 1}
                min={0}
                max={100}
                onChange={(v) => setConfig({ ...config, discord: { ...config.discord, points: { ...config.discord.points, [key]: v } } })}
              />
              <span style={muted}>Punkte</span>
            </div>
          ))}
      </Card>

      <Card title="Eigene Regeln">
        <p style={muted}>Nur was Discords AutoMod nicht kann. Mods, Admins und Server-Administratoren sind immer ausgenommen.</p>
        <Check checked={rules.enabled} onChange={(v) => setRules({ enabled: v })}>
          <strong>Eigene Regeln aktiv</strong>
        </Check>
        {rules.enabled && (
          <>
            <div style={row}>
              <Check checked={rules.flood.on} onChange={(v) => setRules({ flood: { ...rules.flood, on: v } })}>Flut: mehr als</Check>
              <Num value={rules.flood.messages} min={2} max={50} onChange={(v) => setRules({ flood: { ...rules.flood, messages: v } })} />
              Nachrichten in
              <Num value={rules.flood.seconds} min={2} max={120} onChange={(v) => setRules({ flood: { ...rules.flood, seconds: v } })} />
              Sekunden
            </div>
            <div style={row}>
              <Check checked={rules.duplicates.on} onChange={(v) => setRules({ duplicates: { ...rules.duplicates, on: v } })}>Wiederholung:</Check>
              <Num value={rules.duplicates.count} min={2} max={20} onChange={(v) => setRules({ duplicates: { ...rules.duplicates, count: v } })} />
              × derselbe Text in
              <Num value={rules.duplicates.seconds} min={5} max={600} onChange={(v) => setRules({ duplicates: { ...rules.duplicates, seconds: v } })} />
              Sekunden
            </div>
            <div style={row}>
              <Check checked={rules.caps.on} onChange={(v) => setRules({ caps: { ...rules.caps, on: v } })}>Großbuchstaben: ab</Check>
              <Num value={rules.caps.percent} min={50} max={100} onChange={(v) => setRules({ caps: { ...rules.caps, percent: v } })} />
              % bei mindestens
              <Num value={rules.caps.min_length} min={5} max={200} onChange={(v) => setRules({ caps: { ...rules.caps, min_length: v } })} />
              Buchstaben
            </div>
            <div style={row}>
              <Check checked={rules.emojis.on} onChange={(v) => setRules({ emojis: { ...rules.emojis, on: v } })}>Emojis: mehr als</Check>
              <Num value={rules.emojis.max} min={1} max={100} onChange={(v) => setRules({ emojis: { ...rules.emojis, max: v } })} />
            </div>
            <div style={row}>
              Links:
              <select
                value={rules.links.mode}
                onChange={(e) => setRules({ links: { ...rules.links, mode: e.target.value as AutoModRules["links"]["mode"] } })}
              >
                <option value="off">erlaubt</option>
                <option value="allowlist">nur erlaubte Domains</option>
                <option value="block">alle sperren</option>
              </select>
              <span style={muted}>Discord-Einladungen zählen als discord.gg</span>
            </div>
            {rules.links.mode === "allowlist" && (
              <div style={{ margin: "8px 0 8px 24px" }}>
                <div style={muted}>Erlaubte Domains (eine pro Zeile, gilt mit Subdomains):</div>
                <textarea
                  rows={4}
                  style={{ width: 320, background: "var(--wb-bg)", color: "var(--wb-text)", border: "1px solid var(--wb-border)", borderRadius: 4 }}
                  value={allowText}
                  onChange={(e) => setAllowText(e.target.value)}
                  placeholder={"youtube.com\ncommunity.example.com"}
                />
              </div>
            )}
            <div style={row}>
              Hinweis im Alarmkanal bei Konten jünger als
              <Num value={rules.new_accounts_days} min={0} max={365} onChange={(v) => setRules({ new_accounts_days: v })} />
              Tagen <span style={muted}>(0 = aus)</span>
            </div>
          </>
        )}
      </Card>

      {rules.enabled && (
        <>
          <Card title="Folgen bei einem Verstoß">
            <div style={row}>
              <Check checked={rules.action.delete} onChange={(v) => setRules({ action: { ...rules.action, delete: v } })}>Nachricht löschen</Check>
            </div>
            <div style={row}>
              <Num value={rules.action.points} min={0} max={10} onChange={(v) => setRules({ action: { ...rules.action, points: v } })} />
              Warn-Punkte
              <Num value={rules.action.timeout_minutes} min={0} max={1440} onChange={(v) => setRules({ action: { ...rules.action, timeout_minutes: v } })} />
              Minuten Timeout <span style={muted}>(0 = keine)</span>
            </div>
          </Card>

          <Card title="Ausnahmen">
            <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
              <div>
                <div style={muted}>Kanäle (Strg/Cmd für mehrere)</div>
                <MultiSelect items={data.text_channels} selected={rules.exempt_channels} prefix="#" onChange={(ids) => setRules({ exempt_channels: ids })} />
              </div>
              <div>
                <div style={muted}>Rollen</div>
                <MultiSelect items={data.roles} selected={rules.exempt_roles} prefix="@" onChange={(ids) => setRules({ exempt_roles: ids })} />
              </div>
            </div>
          </Card>
        </>
      )}

      <button onClick={() => void save()}>Speichern</button>
      {note && <span style={{ ...muted, marginLeft: 12 }}>{note}</span>}
    </main>
  );
}
