import { useCallback, useEffect, useState, type CSSProperties } from "react";

import { useAuth } from "@/auth/useAuth";

import {
  adoptPanel,
  createPanel,
  deletePanel,
  getRoles,
  saveAutoroles,
  savePanel,
  type Panel,
  type PanelButton,
  type RolesData,
} from "./api";

export const route = { path: "/rollen", navLabel: "Rollen" };

const card: CSSProperties = {
  border: "1px solid var(--wb-border)",
  borderRadius: 8,
  padding: 16,
  background: "var(--wb-surface)",
  marginBottom: 16,
};
const muted: CSSProperties = { color: "var(--wb-text-muted)", fontSize: "0.9em" };
const row: CSSProperties = { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", margin: "8px 0" };
const textarea: CSSProperties = {
  width: "100%",
  maxWidth: 560,
  background: "var(--wb-bg)",
  color: "var(--wb-text)",
  border: "1px solid var(--wb-border)",
  borderRadius: 4,
  fontFamily: "inherit",
};

function RoleSelect({ data, value, onChange, exclude }: { data: RolesData; value: string; onChange: (id: string) => void; exclude: string[] }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">– Rolle wählen –</option>
      {data.roles.map((r) => (
        <option key={r.id} value={r.id} disabled={!!r.blocked || exclude.includes(r.id)} title={r.blocked ?? undefined}>
          @{r.name}
          {r.blocked ? " (nicht vergebbar)" : ""}
        </option>
      ))}
    </select>
  );
}

function roleName(data: RolesData, id: string): string {
  return data.roles.find((r) => r.id === id)?.name ?? "unbekannte Rolle";
}

function Autoroles({ data, onDone }: { data: RolesData; onDone: (msg: string) => void }) {
  const [ids, setIds] = useState<string[]>(data.autoroles);
  const [pick, setPick] = useState("");
  const broken = ids.filter((id) => data.roles.find((r) => r.id === id)?.blocked);

  return (
    <section style={card}>
      <h2 style={{ marginTop: 0 }}>Autorole</h2>
      <p style={muted}>
        Neue Mitglieder bekommen diese Rollen automatisch – bei aktiver Mitgliedschaftsprüfung erst, wenn sie die Regeln
        akzeptiert haben.
      </p>
      {ids.length === 0 && <p style={muted}>Keine.</p>}
      {ids.map((id) => (
        <div key={id} style={row}>
          <strong>@{roleName(data, id)}</strong>
          <button onClick={() => setIds(ids.filter((x) => x !== id))}>Entfernen</button>
        </div>
      ))}
      {broken.length > 0 && (
        <p style={{ ...muted, color: "var(--wb-accent-strong)" }}>
          Nicht vergebbar: {broken.map((id) => data.roles.find((r) => r.id === id)?.blocked).join(" ")}
        </p>
      )}
      <div style={row}>
        <RoleSelect data={data} value={pick} onChange={setPick} exclude={ids} />
        <button
          disabled={!pick}
          onClick={() => {
            setIds([...ids, pick]);
            setPick("");
          }}
        >
          Hinzufügen
        </button>
      </div>
      <button
        onClick={() =>
          saveAutoroles(ids)
            .then((r) => onDone(r.message))
            .catch((e: Error) => onDone(e.message))
        }
      >
        Speichern
      </button>
    </section>
  );
}

function ButtonsEditor({ data, buttons, onChange }: { data: RolesData; buttons: PanelButton[]; onChange: (b: PanelButton[]) => void }) {
  const [pick, setPick] = useState("");
  const set = (index: number, change: Partial<PanelButton>) => onChange(buttons.map((b, i) => (i === index ? { ...b, ...change } : b)));
  const move = (index: number, delta: number) => {
    const next = [...buttons];
    [next[index], next[index + delta]] = [next[index + delta], next[index]];
    onChange(next);
  };

  return (
    <div style={{ margin: "8px 0" }}>
      <div>
        Knöpfe <span style={muted}>(höchstens {data.max_buttons}, je 5 pro Reihe)</span>
      </div>
      {buttons.map((b, i) => (
        <div key={b.role_id} style={row}>
          <span style={{ minWidth: 140 }}>@{roleName(data, b.role_id)}</span>
          <input value={b.emoji} onChange={(e) => set(i, { emoji: e.target.value })} placeholder="Emoji" style={{ width: 70 }} />
          <input value={b.label} onChange={(e) => set(i, { label: e.target.value })} placeholder={roleName(data, b.role_id)} maxLength={80} />
          <button onClick={() => move(i, -1)} disabled={i === 0}>
            ↑
          </button>
          <button onClick={() => move(i, 1)} disabled={i === buttons.length - 1}>
            ↓
          </button>
          <button onClick={() => onChange(buttons.filter((_, j) => j !== i))}>Entfernen</button>
        </div>
      ))}
      <div style={row}>
        <RoleSelect data={data} value={pick} onChange={setPick} exclude={buttons.map((b) => b.role_id)} />
        <button
          disabled={!pick || buttons.length >= data.max_buttons}
          onClick={() => {
            onChange([...buttons, { role_id: pick, label: "", emoji: "" }]);
            setPick("");
          }}
        >
          Knopf hinzufügen
        </button>
      </div>
      <div style={muted}>Emoji: einfach einfügen (z.B. 🦖) oder bei eigenen Server-Emojis die Form &lt;:name:id&gt;.</div>
    </div>
  );
}

function PanelEditor({
  data,
  panel,
  onDone,
  open,
  onToggle,
}: {
  data: RolesData;
  panel: Panel;
  onDone: (msg: string, reload?: boolean) => void;
  open: boolean;
  onToggle: () => void;
}) {
  const [state, setState] = useState({ title: panel.title, text: panel.text, buttons: panel.buttons });

  async function run(action: () => Promise<{ message: string }>) {
    try {
      onDone((await action()).message);
    } catch (e) {
      onDone((e as Error).message, false);
    }
  }

  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }} onClick={onToggle}>
        <span>{open ? "▾" : "▸"}</span>
        <strong style={{ flex: 1 }}>{panel.missing ? "(Nachricht gelöscht)" : panel.title}</strong>
        <span style={muted}>
          #{panel.channel_name ?? "?"} · {panel.buttons.length} Knöpfe
        </span>
      </div>
      {open && (
        <div style={{ marginTop: 12 }}>
          {panel.missing ? (
            <p style={muted}>Die Nachricht gibt es in Discord nicht mehr.</p>
          ) : (
            <>
              {panel.url && (
                <p style={muted}>
                  <a href={panel.url} target="_blank" rel="noreferrer">
                    In Discord öffnen
                  </a>
                </p>
              )}
              <div style={row}>
                Titel: <input value={state.title} onChange={(e) => setState({ ...state, title: e.target.value })} maxLength={256} style={{ minWidth: 280 }} />
              </div>
              <textarea rows={3} style={textarea} value={state.text} onChange={(e) => setState({ ...state, text: e.target.value })} />
              <ButtonsEditor data={data} buttons={state.buttons} onChange={(buttons) => setState({ ...state, buttons })} />
              <button onClick={() => void run(() => savePanel(panel.message_id, state))}>Speichern</button>{" "}
            </>
          )}
          <button
            onClick={() =>
              window.confirm(panel.missing ? "Aus der Liste entfernen?" : "Panel löschen? Die Nachricht in Discord wird gelöscht.") &&
              void run(() => deletePanel(panel.message_id))
            }
          >
            {panel.missing ? "Aus der Liste entfernen" : "Panel löschen"}
          </button>
        </div>
      )}
    </section>
  );
}

function NewPanel({ data, onDone }: { data: RolesData; onDone: (msg: string, reload?: boolean) => void }) {
  const [channel, setChannel] = useState("");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("Klick auf einen Knopf, um dir die Rolle zu geben – nochmal klicken nimmt sie wieder weg.");
  const [buttons, setButtons] = useState<PanelButton[]>([]);
  const [link, setLink] = useState("");

  return (
    <section style={card}>
      <h2 style={{ marginTop: 0 }}>Neues Panel</h2>
      <div style={row}>
        Kanal:
        <select value={channel} onChange={(e) => setChannel(e.target.value)}>
          <option value="">– Kanal wählen –</option>
          {data.text_channels.map((c) => (
            <option key={c.id} value={c.id}>
              #{c.name}
            </option>
          ))}
        </select>
        Titel: <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="z.B. ⚔️ Deine Spiele" maxLength={256} />
      </div>
      <textarea rows={3} style={textarea} value={text} onChange={(e) => setText(e.target.value)} />
      <ButtonsEditor data={data} buttons={buttons} onChange={setButtons} />
      <button
        disabled={!channel || !title.trim()}
        onClick={() =>
          createPanel({ channel_id: channel, title: title.trim(), text, buttons })
            .then((r) => onDone(r.message))
            .catch((e: Error) => onDone(e.message, false))
        }
      >
        Panel posten
      </button>
      <div style={{ ...row, marginTop: 16 }}>
        <span style={muted}>Schon ein Panel per /rollen erstellt?</span>
        <input value={link} onChange={(e) => setLink(e.target.value)} placeholder="Nachrichten-Link" style={{ minWidth: 260 }} />
        <button
          disabled={!link.trim()}
          onClick={() =>
            adoptPanel(link.trim())
              .then((r) => onDone(r.message))
              .catch((e: Error) => onDone(e.message, false))
          }
        >
          Übernehmen
        </button>
      </div>
    </section>
  );
}

export default function RolesPage() {
  const { user } = useAuth();
  const isAdmin = user?.level === "admin" || user?.level === "owner";
  const [data, setData] = useState<RolesData | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [generation, setGeneration] = useState(0);
  const [openIds, setOpenIds] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setData(await getRoles());
    setGeneration((g) => g + 1);
  }, []);

  useEffect(() => {
    if (isAdmin) load().catch((e: Error) => setNote(e.message));
  }, [isAdmin, load]);

  if (!isAdmin) return <main style={{ padding: 24 }}>Nur für Admins.</main>;
  if (!data) return <main style={{ padding: 24 }}>{note ?? "Lädt…"}</main>;

  const done = (message: string, reload = true) => {
    setNote(message);
    if (reload) void load();
  };

  return (
    <main style={{ padding: 24, maxWidth: 960 }}>
      <h1>Rollen</h1>
      <p style={muted}>
        Rollen mit Verwaltungsrechten, Rollen über dem Bot und die Berechtigungsrollen des Bots (Tab Einstellungen) sind
        ausgegraut – die vergibt der Bot aus Sicherheitsgründen nicht.
      </p>
      {!data.cog_loaded && <p style={{ ...card, borderColor: "var(--wb-border-strong)" }}>Der Rollen-Cog ist nicht geladen.</p>}
      {note && <p style={{ ...card, padding: "8px 12px" }}>{note}</p>}

      <Autoroles key={`auto-${generation}`} data={data} onDone={done} />

      <h2>Selbstwahl-Panels</h2>
      {data.panels.length === 0 && <p style={muted}>Noch keine Panels.</p>}
      {data.panels.map((panel) => (
        <PanelEditor
          key={`${panel.message_id}-${generation}`}
          data={data}
          panel={panel}
          onDone={done}
          open={openIds.has(panel.message_id)}
          onToggle={() => {
            const next = new Set(openIds);
            if (!next.delete(panel.message_id)) next.add(panel.message_id);
            setOpenIds(next);
          }}
        />
      ))}
      <NewPanel key={`new-${generation}`} data={data} onDone={done} />
    </main>
  );
}
