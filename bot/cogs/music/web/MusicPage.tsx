import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from "react";

import { useAuth } from "@/auth/useAuth";

import {
  addPodcast,
  addStation,
  control,
  getConfig,
  getEpisodes,
  getLibrary,
  getState,
  play,
  removePodcast,
  removeStation,
  setAnnounce,
} from "./api";
import type { ControlAction, EpisodeItem, Library, MusicConfig, MusicState, PlayKind } from "./types";

export const route = { path: "/music", navLabel: "Musik" };

const card: CSSProperties = {
  border: "1px solid var(--wb-border)",
  borderRadius: 8,
  padding: 16,
  background: "var(--wb-surface)",
  marginBottom: 16,
};
const muted: CSSProperties = { color: "var(--wb-text-muted)", fontSize: "0.9em" };
const row: CSSProperties = { display: "flex", alignItems: "center", gap: 8, padding: "4px 0" };

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={card}>
      <h2 style={{ marginTop: 0 }}>{title}</h2>
      {children}
    </section>
  );
}

export default function MusicPage() {
  const { user } = useAuth();
  const isAdmin = user?.level === "admin" || user?.level === "owner";

  const [state, setState] = useState<MusicState | null>(null);
  const [library, setLibrary] = useState<Library | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refreshState = useCallback(async () => {
    try {
      setState(await getState());
    } catch (error) {
      setMessage((error as Error).message);
    }
  }, []);

  const refreshLibrary = useCallback(async () => {
    setLibrary(await getLibrary());
  }, []);

  useEffect(() => {
    void refreshState();
    void refreshLibrary();
    const timer = window.setInterval(() => void refreshState(), 3000);
    return () => window.clearInterval(timer);
  }, [refreshState, refreshLibrary]);

  async function run(action: () => Promise<unknown>, success?: string) {
    setBusy(true);
    setMessage(null);
    try {
      await action();
      if (success) setMessage(success);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
      void refreshState();
    }
  }

  const doPlay = (kind: PlayKind, name: string, episode = 0, shuffle = false) =>
    run(() => play(kind, name, episode, shuffle));
  const doControl = (action: ControlAction, value?: number) => run(() => control(action, value));

  return (
    <main style={{ padding: 24, maxWidth: 960 }}>
      <h1>Musik</h1>
      {message && (
        <p style={{ ...card, borderColor: "var(--wb-border-strong)", padding: "8px 12px" }}>{message}</p>
      )}

      <NowPlaying state={state} busy={busy} onControl={doControl} />

      {state && !state.my_channel_name && (
        <p style={muted}>
          Geh in Discord in einen Voice-Kanal – dann kannst du hier abspielen. Die Musik kommt in deinen Kanal.
        </p>
      )}

      <Card title="Radio">
        {library?.stations.length === 0 && <p style={muted}>Noch keine Sender eingetragen.</p>}
        {library?.stations.map((name) => (
          <div key={name} style={row}>
            <button disabled={busy} onClick={() => void doPlay("radio", name)}>
              ▶
            </button>
            {name}
          </div>
        ))}
      </Card>

      <Podcasts names={library?.podcasts ?? []} busy={busy} onPlay={(name, episode) => void doPlay("podcast", name, episode)} />

      <Files library={library} busy={busy} onPlay={(kind, name, shuffle) => void doPlay(kind, name, 0, shuffle)} />

      {isAdmin && <AdminSettings onChange={() => void refreshLibrary()} />}
    </main>
  );
}

function NowPlaying({
  state,
  busy,
  onControl,
}: {
  state: MusicState | null;
  busy: boolean;
  onControl: (action: ControlAction, value?: number) => void;
}) {
  const [volume, setVolume] = useState<number | null>(null);
  if (state === null) return <section style={card}>Lädt…</section>;
  const disabled = busy || !state.can_control || !state.connected;
  return (
    <Card title="Jetzt">
      {!state.connected && <p style={muted}>Der Bot ist in keinem Voice-Kanal.</p>}
      {state.connected && (
        <>
          <p>
            {state.current ? (
              <>
                {state.paused ? "⏸️" : "▶️"} <strong>{state.current.title}</strong>{" "}
                <span style={muted}>({state.current.label})</span>
              </>
            ) : (
              <span style={muted}>Es läuft gerade nichts.</span>
            )}
            <br />
            <span style={muted}>in {state.channel_name}</span>
          </p>
          <div style={{ ...row, flexWrap: "wrap" }}>
            {state.paused ? (
              <button disabled={disabled} onClick={() => onControl("resume")}>▶ Weiter</button>
            ) : (
              <button disabled={disabled} onClick={() => onControl("pause")}>⏸ Pause</button>
            )}
            <button disabled={disabled} onClick={() => onControl("skip")}>⏭ Skip</button>
            <button disabled={disabled} onClick={() => onControl("shuffle")}>🔀 Mischen</button>
            <button disabled={disabled} onClick={() => onControl("stop")}>⏹ Stopp</button>
            <label style={{ marginLeft: 12 }}>
              🔊{" "}
              <input
                type="range"
                min={0}
                max={100}
                disabled={disabled}
                value={volume ?? state.volume}
                onChange={(e) => setVolume(Number(e.target.value))}
                onMouseUp={() => volume !== null && onControl("volume", volume)}
                onTouchEnd={() => volume !== null && onControl("volume", volume)}
                onKeyUp={() => volume !== null && onControl("volume", volume)}
              />{" "}
              {volume ?? state.volume}
            </label>
          </div>
          {!state.can_control && (
            <p style={muted}>Steuern darf, wer im selben Voice-Kanal ist – oder ein Mod.</p>
          )}
          {state.queue.length > 0 && (
            <>
              <h3>Warteschlange ({state.queue_length})</h3>
              <ol style={{ margin: 0 }}>
                {state.queue.map((track, index) => (
                  <li key={index}>
                    {track.title} <span style={muted}>({track.label})</span>
                  </li>
                ))}
              </ol>
              {state.queue_length > state.queue.length && (
                <p style={muted}>… und {state.queue_length - state.queue.length} weitere</p>
              )}
            </>
          )}
        </>
      )}
    </Card>
  );
}

function Podcasts({
  names,
  busy,
  onPlay,
}: {
  names: string[];
  busy: boolean;
  onPlay: (name: string, episode: number) => void;
}) {
  const [selected, setSelected] = useState("");
  const [episodes, setEpisodes] = useState<EpisodeItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!selected) return;
    setEpisodes(null);
    setError(null);
    getEpisodes(selected)
      .then(setEpisodes)
      .catch((e: Error) => setError(e.message));
  }, [selected]);

  return (
    <Card title="Podcasts">
      {names.length === 0 && <p style={muted}>Noch keine Podcasts eingetragen.</p>}
      {names.length > 0 && (
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          <option value="">– Podcast wählen –</option>
          {names.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      )}
      {error && <p style={muted}>{error}</p>}
      {selected && episodes === null && !error && <p style={muted}>Lädt…</p>}
      <div style={{ maxHeight: 320, overflowY: "auto", marginTop: 8 }}>
        {episodes?.map((episode) => (
          <div key={episode.index} style={row}>
            <button disabled={busy} onClick={() => onPlay(selected, episode.index)}>
              ▶
            </button>
            <span style={{ ...muted, minWidth: 80 }}>{episode.published}</span>
            {episode.title}
          </div>
        ))}
      </div>
    </Card>
  );
}

function Files({
  library,
  busy,
  onPlay,
}: {
  library: Library | null;
  busy: boolean;
  onPlay: (kind: PlayKind, name: string, shuffle?: boolean) => void;
}) {
  const [filter, setFilter] = useState("");
  if (!library) return null;
  const files = library.files.filter((f) => f.toLowerCase().includes(filter.toLowerCase()));
  return (
    <Card title="Eigene Dateien">
      {library.files.length === 0 && (
        <p style={muted}>Keine Dateien. Sie gehören in AMP in den Ordner Wikingerbot-main/data/music.</p>
      )}
      {library.folders.length > 0 && (
        <>
          <h3>Ordner</h3>
          {library.folders.map((folder) => (
            <div key={folder} style={row}>
              <button disabled={busy} onClick={() => onPlay("folder", folder)}>
                ▶
              </button>
              <button disabled={busy} onClick={() => onPlay("folder", folder, true)} title="zufällige Reihenfolge">
                🔀
              </button>
              {folder === "." ? "Hauptordner" : folder}
            </div>
          ))}
        </>
      )}
      {library.files.length > 0 && (
        <>
          <h3>Dateien</h3>
          <input placeholder="Suchen…" value={filter} onChange={(e) => setFilter(e.target.value)} />
          <div style={{ maxHeight: 320, overflowY: "auto", marginTop: 8 }}>
            {files.map((file) => (
              <div key={file} style={row}>
                <button disabled={busy} onClick={() => onPlay("file", file)}>
                  ▶
                </button>
                {file}
              </div>
            ))}
          </div>
        </>
      )}
    </Card>
  );
}

function AdminSettings({ onChange }: { onChange: () => void }) {
  const [config, setConfig] = useState<MusicConfig | null>(null);
  const [station, setStation] = useState({ name: "", url: "" });
  const [podcast, setPodcast] = useState({ name: "", url: "" });
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => setConfig(await getConfig()), []);
  useEffect(() => {
    void load();
  }, [load]);

  async function act(action: () => Promise<unknown>, success: string) {
    setNote(null);
    try {
      await action();
      setNote(success);
      await load();
      onChange();
    } catch (error) {
      setNote((error as Error).message);
    }
  }

  if (!config) return null;
  return (
    <Card title="Einstellungen (Admin)">
      {note && <p style={muted}>{note}</p>}

      <h3>Radiosender</h3>
      {config.stations.map((s) => (
        <div key={s.name} style={row}>
          <strong>{s.name}</strong>
          <span style={{ ...muted, overflow: "hidden", textOverflow: "ellipsis" }}>{s.url}</span>
          <button onClick={() => void act(() => removeStation(s.name), `${s.name} entfernt.`)}>Entfernen</button>
        </div>
      ))}
      <div style={{ ...row, flexWrap: "wrap" }}>
        <input placeholder="Name" value={station.name} onChange={(e) => setStation({ ...station, name: e.target.value })} />
        <input
          placeholder="Stream-Adresse oder .m3u/.pls"
          style={{ flex: 1, minWidth: 240 }}
          value={station.url}
          onChange={(e) => setStation({ ...station, url: e.target.value })}
        />
        <button
          disabled={!station.name || !station.url}
          onClick={() =>
            void act(() => addStation(station.name, station.url), `${station.name} eingetragen.`).then(() =>
              setStation({ name: "", url: "" }),
            )
          }
        >
          Hinzufügen
        </button>
      </div>

      <h3>Podcasts</h3>
      {config.podcasts.map((p) => (
        <div key={p.name} style={{ ...row, flexWrap: "wrap" }}>
          <strong>{p.name}</strong>
          <label style={muted}>
            Neue Folgen ankündigen in{" "}
            <select
              value={p.channel_id ?? ""}
              onChange={(e) =>
                void act(() => setAnnounce(p.name, e.target.value || null), "Ankündigung gespeichert.")
              }
            >
              <option value="">– aus –</option>
              {config.text_channels.map((c) => (
                <option key={c.id} value={c.id}>
                  #{c.name}
                </option>
              ))}
            </select>
          </label>
          <button onClick={() => void act(() => removePodcast(p.name), `${p.name} entfernt.`)}>Entfernen</button>
        </div>
      ))}
      <div style={{ ...row, flexWrap: "wrap" }}>
        <input placeholder="Kurzname" value={podcast.name} onChange={(e) => setPodcast({ ...podcast, name: e.target.value })} />
        <input
          placeholder="Adresse des RSS-Feeds"
          style={{ flex: 1, minWidth: 240 }}
          value={podcast.url}
          onChange={(e) => setPodcast({ ...podcast, url: e.target.value })}
        />
        <button
          disabled={!podcast.name || !podcast.url}
          onClick={() =>
            void act(() => addPodcast(podcast.name, podcast.url), `${podcast.name} eingetragen.`).then(() =>
              setPodcast({ name: "", url: "" }),
            )
          }
        >
          Abonnieren
        </button>
      </div>

      <h3>Eigene Dateien</h3>
      <p style={muted}>
        {config.file_count} Dateien. Hochladen über den AMP-Dateimanager nach <code>Wikingerbot-main/data/music</code>;
        Unterordner sind Playlisten. Erlaubt: mp3, ogg, opus, flac, wav, m4a, aac.
      </p>
    </Card>
  );
}
