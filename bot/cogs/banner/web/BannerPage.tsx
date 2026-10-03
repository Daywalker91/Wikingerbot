import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from "react";

import { useAuth } from "@/auth/useAuth";

import {
  createGroup,
  deleteGroup,
  getBanner,
  previewUrl,
  refreshGroup,
  refreshServer,
  saveGroup,
  saveServer,
  uploadBackground,
  type Background,
  type BannerData,
  type GroupBanner,
  type ServerBanner,
  type Style,
} from "./api";

export const route = { path: "/banner", navLabel: "Banner" };

const card: CSSProperties = {
  border: "1px solid var(--wb-border)",
  borderRadius: 8,
  padding: 16,
  background: "var(--wb-surface)",
  marginBottom: 16,
};
const muted: CSSProperties = { color: "var(--wb-text-muted)", fontSize: "0.9em" };
const row: CSSProperties = { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", margin: "8px 0" };

const BACKGROUND_LABELS: Record<Background, string> = {
  steam: "Steam-Artwork",
  image: "Eigenes Bild",
  theme: "Theme",
  colors: "Eigener Verlauf",
};

function ChannelSelect({ data, value, onChange }: { data: BannerData; value: string | null; onChange: (v: string | null) => void }) {
  return (
    <select value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">– Kanal wählen –</option>
      {data.text_channels.map((c) => (
        <option key={c.id} value={c.id}>
          #{c.name}
        </option>
      ))}
    </select>
  );
}

function ColorField({
  label,
  value,
  presets,
  onChange,
  allowEmpty,
}: {
  label: string;
  value: string | null;
  presets: Record<string, string>;
  onChange: (v: string | null) => void;
  allowEmpty?: string;
}) {
  return (
    <div style={row}>
      <span style={{ minWidth: 110 }}>{label}</span>
      <input type="color" value={value ?? "#ffffff"} onChange={(e) => onChange(e.target.value)} />
      <select value="" onChange={(e) => e.target.value && onChange(e.target.value)} title="Vorgabe wählen">
        <option value="">Vorgabe …</option>
        {Object.entries(presets).map(([name, hex]) => (
          <option key={hex} value={hex}>
            {name}
          </option>
        ))}
      </select>
      {allowEmpty && (
        <button onClick={() => onChange(null)} disabled={value === null}>
          {allowEmpty}
        </button>
      )}
      {value && <code style={muted}>{value}</code>}
    </div>
  );
}

/** Darstellung und Hintergrund - gemeinsam fuer Server und Gruppen. */
function StyleEditor({
  data,
  style,
  onChange,
  steamAvailable,
  hasImage,
  onUpload,
}: {
  data: BannerData;
  style: Style;
  onChange: (change: Partial<Style>) => void;
  steamAvailable: boolean;
  hasImage: boolean;
  onUpload: ((file: File) => void) | null;
}) {
  const modes: Background[] = [...(steamAvailable ? (["steam"] as Background[]) : []), "image", "theme", "colors"];
  return (
    <>
      <div style={row}>
        Darstellung:
        <label>
          <input type="radio" checked={style.type === "embed"} onChange={() => onChange({ type: "embed" })} /> Embed
        </label>
        <label>
          <input type="radio" checked={style.type === "image"} onChange={() => onChange({ type: "image" })} /> Bild
        </label>
      </div>
      {style.type === "image" && (
        <>
          <div style={row}>
            Hintergrund:
            {modes.map((mode) => (
              <label key={mode}>
                <input
                  type="radio"
                  checked={style.background === mode}
                  onChange={() =>
                    onChange({
                      background: mode,
                      ...(mode === "colors" && !style.color_start ? { color_start: "#0f2027", color_end: "#2c5364" } : {}),
                    })
                  }
                />{" "}
                {BACKGROUND_LABELS[mode]}
              </label>
            ))}
          </div>
          {style.background === "image" && (
            <div style={row}>
              {onUpload ? (
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  onChange={(e) => e.target.files?.[0] && onUpload(e.target.files[0])}
                />
              ) : (
                <span style={muted}>Bild hochladen geht, sobald die Gruppe angelegt ist.</span>
              )}
              <span style={muted}>{hasImage ? "Bild vorhanden – ein neues ersetzt es." : "PNG, JPEG oder WebP, max. 8 MB"}</span>
            </div>
          )}
          {style.background === "theme" && (
            <div style={row}>
              Theme:
              <select value={style.theme} onChange={(e) => onChange({ theme: e.target.value })}>
                {Object.keys(data.themes).map((key) => (
                  <option key={key} value={key}>
                    {key.charAt(0).toUpperCase() + key.slice(1)}
                  </option>
                ))}
              </select>
            </div>
          )}
          {style.background === "colors" && (
            <>
              <ColorField label="Farbe oben" value={style.color_start} presets={data.presets} onChange={(v) => onChange({ color_start: v })} />
              <ColorField label="Farbe unten" value={style.color_end} presets={data.presets} onChange={(v) => onChange({ color_end: v })} />
            </>
          )}
          <ColorField
            label="Schriftfarbe"
            value={style.text_color}
            presets={data.presets}
            onChange={(v) => onChange({ text_color: v })}
            allowEmpty="Standard (weiß)"
          />
          <div style={row}>
            Unschärfe:
            <select value={style.blur} onChange={(e) => onChange({ blur: Number(e.target.value) })}>
              {Object.entries(data.blur_levels).map(([name, radius]) => (
                <option key={radius} value={radius}>
                  {name}
                </option>
              ))}
            </select>
          </div>
        </>
      )}
    </>
  );
}

/** Live-Vorschau: Bild vom Bot gerendert (verzoegert, damit nicht jeder Klick rendert). */
function Preview({ kind, id, style, members, version }: { kind: "servers" | "groups"; id: number; style: Style; members?: number[]; version: number }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = JSON.stringify([kind, id, style, members, version]);

  useEffect(() => {
    if (style.type !== "image") return;
    let created: string | null = null;
    const timer = setTimeout(() => {
      previewUrl(kind, id, style, members)
        .then((next) => {
          created = next;
          setUrl(next);
          setError(null);
        })
        .catch((e: Error) => setError(e.message));
    }, 400);
    return () => {
      clearTimeout(timer);
      if (created) URL.revokeObjectURL(created);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  if (style.type !== "image") {
    return <p style={muted}>Als Embed zeigt Discord Status, Spieler, Uptime und Whitelist als Textfelder – darüber steht die Adresse zum Kopieren.</p>;
  }
  if (error) return <p style={muted}>{error}</p>;
  if (!url) return <p style={muted}>Vorschau lädt…</p>;
  return (
    <div>
      <img src={url} alt="Banner-Vorschau" style={{ maxWidth: "100%", borderRadius: 8, display: "block" }} />
      <div style={muted}>Vorschau mit Beispielwerten (3/10 Spieler)</div>
    </div>
  );
}

function Section({ title, open, onToggle, extra, children }: { title: ReactNode; open: boolean; onToggle: () => void; extra?: ReactNode; children: ReactNode }) {
  return (
    <section style={card}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer" }} onClick={onToggle}>
        <span>{open ? "▾" : "▸"}</span>
        <strong style={{ flex: 1 }}>{title}</strong>
        {extra}
      </div>
      {open && <div style={{ marginTop: 12 }}>{children}</div>}
    </section>
  );
}

function ServerEditor({
  data,
  server,
  onDone,
  open,
  onToggle,
}: {
  data: BannerData;
  server: ServerBanner;
  onDone: (msg: string) => void;
  open: boolean;
  onToggle: () => void;
}) {
  const [state, setState] = useState<ServerBanner>(server);
  const [version, setVersion] = useState(0);
  const group = data.groups.find((g) => g.id === server.group_id);
  const change = (c: Partial<ServerBanner>) => setState({ ...state, ...c });

  async function run(action: () => Promise<{ message: string }>) {
    try {
      onDone((await action()).message);
    } catch (e) {
      onDone((e as Error).message);
    }
  }

  const status = group ? `in Gruppe „${group.name}“` : server.enabled ? "aktiv" : "aus";
  return (
    <Section title={server.name} open={open} onToggle={onToggle} extra={<span style={muted}>{status}</span>}>
      {group ? (
        <p style={muted}>
          Dieser Server erscheint im Banner der Gruppe „{group.name}“. Sein eigenes Aussehen gilt dort nur im Layout „Einzeln“.
        </p>
      ) : (
        <div style={row}>
          <label>
            <input type="checkbox" checked={state.enabled} onChange={(e) => change({ enabled: e.target.checked })} /> Banner aktiv
          </label>
          in
          <ChannelSelect data={data} value={state.channel_id} onChange={(v) => change({ channel_id: v })} />
        </div>
      )}
      <StyleEditor
        data={data}
        style={state}
        onChange={change}
        steamAvailable={server.steam_art}
        hasImage={state.has_image}
        onUpload={(file) =>
          void run(async () => {
            const result = await uploadBackground("servers", server.id, file);
            setState({ ...state, has_image: true, background: "image" });
            setVersion(version + 1);
            return result;
          })
        }
      />
      <Preview kind="servers" id={server.id} style={state} version={version} />
      <div style={{ ...row, marginTop: 12 }}>
        <button onClick={() => void run(() => saveServer(server.id, state))}>Speichern</button>
        {server.enabled && !group && <button onClick={() => void run(() => refreshServer(server.id))}>Jetzt aktualisieren</button>}
      </div>
    </Section>
  );
}

const NEW_GROUP: GroupBanner = {
  id: 0,
  name: "",
  channel_id: null,
  layout: "combined",
  member_ids: [],
  has_image: false,
  type: "image",
  background: "theme",
  theme: "midnight",
  color_start: null,
  color_end: null,
  text_color: null,
  blur: 0,
};

function GroupEditor({
  data,
  group,
  onDone,
  open,
  onToggle,
}: {
  data: BannerData;
  group: GroupBanner;
  onDone: (msg: string, reload?: boolean) => void;
  open: boolean;
  onToggle: () => void;
}) {
  const [state, setState] = useState<GroupBanner>(group);
  const [version, setVersion] = useState(0);
  const isNew = group.id === 0;
  const change = (c: Partial<GroupBanner>) => setState({ ...state, ...c });
  const free = data.servers.filter((s) => s.group_id === null || s.group_id === group.id);

  async function run(action: () => Promise<{ message: string }>, reload = true) {
    try {
      onDone((await action()).message, reload);
    } catch (e) {
      onDone((e as Error).message, false);
    }
  }

  function toggleMember(id: number, on: boolean) {
    const next = on ? [...state.member_ids, id] : state.member_ids.filter((m) => m !== id);
    if (next.length > data.max_group_members) return;
    change({ member_ids: next });
  }

  const title = isNew ? "Neue Gruppe" : group.name;
  return (
    <Section title={title} open={open} onToggle={onToggle} extra={!isNew && <span style={muted}>{group.member_ids.length} Server</span>}>
      <div style={row}>
        Name:
        <input value={state.name} onChange={(e) => change({ name: e.target.value })} placeholder="z.B. Survival-Server" />
        Kanal:
        <ChannelSelect data={data} value={state.channel_id} onChange={(v) => change({ channel_id: v })} />
      </div>
      <div style={row}>
        Layout:
        <label>
          <input type="radio" checked={state.layout === "combined"} onChange={() => change({ layout: "combined" })} /> Kombiniert
        </label>
        <label>
          <input type="radio" checked={state.layout === "separate"} onChange={() => change({ layout: "separate" })} /> Einzeln
        </label>
        <span style={muted}>
          {state.layout === "combined" ? "ein gemeinsames Bild/Embed" : "ein Bild/Embed pro Server mit dessen eigenem Aussehen"}
        </span>
      </div>
      <div style={{ margin: "8px 0" }}>
        <div>
          Server <span style={muted}>(max. {data.max_group_members}; ein eigener Banner wird dabei abgeschaltet)</span>
        </div>
        {free.length === 0 && <div style={muted}>Keine freien Server.</div>}
        {free.map((s) => (
          <label key={s.id} style={{ display: "inline-block", marginRight: 16 }}>
            <input type="checkbox" checked={state.member_ids.includes(s.id)} onChange={(e) => toggleMember(s.id, e.target.checked)} /> {s.name}
          </label>
        ))}
      </div>
      {state.layout === "combined" ? (
        <>
          <StyleEditor
            data={data}
            style={state}
            onChange={change}
            steamAvailable={false}
            hasImage={state.has_image}
            onUpload={
              isNew
                ? null
                : (file) =>
                    void run(async () => {
                      const result = await uploadBackground("groups", group.id, file);
                      setState({ ...state, has_image: true, background: "image" });
                      setVersion(version + 1);
                      return result;
                    }, false)
            }
          />
          <Preview kind="groups" id={group.id} style={state} members={state.member_ids} version={version} />
        </>
      ) : (
        <div style={row}>
          Darstellung:
          <label>
            <input type="radio" checked={state.type === "embed"} onChange={() => change({ type: "embed" })} /> Embed
          </label>
          <label>
            <input type="radio" checked={state.type === "image"} onChange={() => change({ type: "image" })} /> Bild
          </label>
          <span style={muted}>Das Aussehen stellst du beim jeweiligen Server ein.</span>
        </div>
      )}
      <div style={{ ...row, marginTop: 12 }}>
        {isNew ? (
          <button
            disabled={!state.name.trim() || !state.channel_id}
            onClick={() =>
              void run(async () => {
                const result = await createGroup({ ...state, name: state.name.trim() });
                setState(NEW_GROUP);
                return result;
              })
            }
          >
            Gruppe anlegen
          </button>
        ) : (
          <>
            <button onClick={() => void run(() => saveGroup(group.id, { ...state, name: state.name.trim() }))}>Speichern</button>
            <button onClick={() => void run(() => refreshGroup(group.id), false)}>Jetzt aktualisieren</button>
            <button
              onClick={() =>
                window.confirm(`Gruppe „${group.name}“ auflösen? Ihre Server werden wieder frei, der Gruppen-Banner wird gelöscht.`) &&
                void run(() => deleteGroup(group.id))
              }
            >
              Auflösen
            </button>
          </>
        )}
      </div>
    </Section>
  );
}

export default function BannerPage() {
  const { user } = useAuth();
  const [data, setData] = useState<BannerData | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [generation, setGeneration] = useState(0);
  const [openIds, setOpenIds] = useState<Set<string>>(new Set());
  const toggle = (id: string) => () => {
    const next = new Set(openIds);
    if (!next.delete(id)) next.add(id);
    setOpenIds(next);
  };

  const load = useCallback(async () => {
    setData(await getBanner());
    setGeneration((g) => g + 1); // Editoren mit frischen Werten neu aufbauen
  }, []);

  useEffect(() => {
    if (user?.level === "owner") load().catch((e: Error) => setNote(e.message));
  }, [user?.level, load]);

  if (user?.level !== "owner") return <main style={{ padding: 24 }}>Nur für den Owner.</main>;
  if (!data) return <main style={{ padding: 24 }}>{note ?? "Lädt…"}</main>;

  const done = (message: string, reload = true) => {
    setNote(message);
    if (reload) void load();
  };

  return (
    <main style={{ padding: 24, maxWidth: 960 }}>
      <h1>Banner</h1>
      <p style={muted}>
        Ein Status-Banner pro Server oder für eine Gruppe von Servern – der Bot aktualisiert ihn jede Minute. Über dem Banner steht
        die Verbindungsadresse zum Kopieren.
      </p>
      {!data.cog_loaded && (
        <p style={{ ...card, borderColor: "var(--wb-border-strong)" }}>Der Banner-Cog ist nicht geladen – Einstellungen werden nur gespeichert.</p>
      )}
      {note && <p style={{ ...card, padding: "8px 12px" }}>{note}</p>}

      <h2>Server</h2>
      {data.servers.length === 0 && <p style={muted}>Noch keine Server angelegt (Tab Server).</p>}
      {data.servers.map((server) => (
        <ServerEditor
          key={`${server.id}-${generation}`}
          data={data}
          server={server}
          onDone={done}
          open={openIds.has(`s${server.id}`)}
          onToggle={toggle(`s${server.id}`)}
        />
      ))}

      <h2>Gruppen</h2>
      <p style={muted}>Mehrere Server in einem gemeinsamen Banner, z.B. alle Server eines Spiels.</p>
      {data.groups.map((group) => (
        <GroupEditor
          key={`${group.id}-${generation}`}
          data={data}
          group={group}
          onDone={done}
          open={openIds.has(`g${group.id}`)}
          onToggle={toggle(`g${group.id}`)}
        />
      ))}
      <GroupEditor key={`new-${generation}`} data={data} group={NEW_GROUP} onDone={done} open={openIds.has("new")} onToggle={toggle("new")} />
    </main>
  );
}
