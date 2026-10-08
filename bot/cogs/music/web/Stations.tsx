import { useMemo, useState, type CSSProperties } from "react";

import { addStation, bulkStations, importStations, removeStation } from "./api";
import type { StationItem } from "./types";

/** Radiosender mit Suche und Kategorien - Abspielliste (alle) und Verwaltung (Admin). */

export const NO_CATEGORY = "Ohne Kategorie";
const SHOW_PLAY = 100; // so viele Treffer zeigt die Abspielliste
const SHOW_ADMIN = 200;

const muted: CSSProperties = { color: "var(--wb-text-muted)", fontSize: "0.9em" };
const row: CSSProperties = { display: "flex", alignItems: "center", gap: 8, padding: "4px 0" };
const tag: CSSProperties = {
  border: "1px solid var(--wb-border)",
  borderRadius: 10,
  padding: "0 8px",
  fontSize: "0.8em",
  color: "var(--wb-text-muted)",
};

function categoriesOf(stations: StationItem[]): string[] {
  return [...new Set(stations.map((s) => s.category).filter(Boolean))].sort((a, b) => a.localeCompare(b, "de"));
}

/** Wie im Bot: alle Woerter muessen in Name oder Kategorie vorkommen; category "" = alle. */
function filterStations<T extends StationItem>(stations: T[], query: string, category: string): T[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  return stations.filter((s) => {
    if (category === NO_CATEGORY ? s.category !== "" : category && s.category !== category) return false;
    const haystack = `${s.name} ${s.category}`.toLowerCase();
    return words.every((w) => haystack.includes(w));
  });
}

function Filter({
  stations,
  query,
  category,
  onQuery,
  onCategory,
}: {
  stations: StationItem[];
  query: string;
  category: string;
  onQuery: (value: string) => void;
  onCategory: (value: string) => void;
}) {
  const categories = categoriesOf(stations);
  const hasUncategorized = stations.some((s) => !s.category);
  return (
    <div style={{ ...row, flexWrap: "wrap" }}>
      <input placeholder="Suchen (Name oder Kategorie)" style={{ flex: 1, minWidth: 200 }} value={query} onChange={(e) => onQuery(e.target.value)} />
      <select value={category} onChange={(e) => onCategory(e.target.value)}>
        <option value="">Alle Kategorien</option>
        {categories.map((c) => (
          <option key={c} value={c}>
            {c} ({stations.filter((s) => s.category === c).length})
          </option>
        ))}
        {hasUncategorized && categories.length > 0 && <option value={NO_CATEGORY}>{NO_CATEGORY}</option>}
      </select>
    </div>
  );
}

export function RadioList({ stations, busy, onPlay }: { stations: StationItem[]; busy: boolean; onPlay: (name: string) => void }) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const hits = useMemo(() => filterStations(stations, query, category), [stations, query, category]);

  if (stations.length === 0) return <p style={muted}>Noch keine Sender eingetragen.</p>;
  return (
    <>
      <Filter stations={stations} query={query} category={category} onQuery={setQuery} onCategory={setCategory} />
      {hits.length === 0 && <p style={muted}>Keine passenden Sender.</p>}
      {hits.slice(0, SHOW_PLAY).map((s) => (
        <div key={s.name} style={row}>
          <button disabled={busy} onClick={() => onPlay(s.name)}>
            ▶
          </button>
          {s.name}
          {s.category && !category && <span style={tag}>{s.category}</span>}
        </div>
      ))}
      {hits.length > SHOW_PLAY && (
        <p style={muted}>
          … und {hits.length - SHOW_PLAY} weitere – Suche oder Kategorie eingrenzen.
        </p>
      )}
    </>
  );
}

export function StationAdmin({
  stations,
  act,
}: {
  stations: (StationItem & { url: string })[];
  act: (action: () => Promise<unknown>, success: string | ((result: unknown) => string)) => Promise<boolean>;
}) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [target, setTarget] = useState("");
  const [station, setStation] = useState({ name: "", url: "", category: "" });
  const [importUrl, setImportUrl] = useState("");
  const [importCategory, setImportCategory] = useState("");

  const hits = useMemo(() => filterStations(stations, query, category), [stations, query, category]);
  const shown = hits.slice(0, SHOW_ADMIN);
  const chosen = [...selected].filter((name) => stations.some((s) => s.name === name));
  const allShownSelected = shown.length > 0 && shown.every((s) => selected.has(s.name));

  function toggle(name: string) {
    const next = new Set(selected);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    setSelected(next);
  }

  function selectHits(on: boolean) {
    const next = new Set(selected);
    for (const s of hits) {
      if (on) next.add(s.name);
      else next.delete(s.name);
    }
    setSelected(next);
  }

  async function bulk(action: "category" | "delete", value = "") {
    const ok = await act(() => bulkStations(chosen, action, value), (r) => (r as { message: string }).message);
    if (ok) setSelected(new Set());
  }

  return (
    <>
      <datalist id="music-categories">
        {categoriesOf(stations).map((c) => (
          <option key={c} value={c} />
        ))}
      </datalist>

      <Filter stations={stations} query={query} category={category} onQuery={setQuery} onCategory={setCategory} />
      <div style={{ ...row, flexWrap: "wrap" }}>
        <label>
          <input type="checkbox" checked={allShownSelected} onChange={(e) => selectHits(e.target.checked)} /> Alle{" "}
          {hits.length} Treffer auswählen
        </label>
        {chosen.length > 0 && (
          <>
            <span style={muted}>{chosen.length} ausgewählt:</span>
            <input list="music-categories" placeholder="Kategorie (leer = keine)" value={target} onChange={(e) => setTarget(e.target.value)} />
            <button onClick={() => void bulk("category", target)}>Kategorie setzen</button>
            <button
              onClick={() => {
                if (window.confirm(`${chosen.length} Sender wirklich entfernen?`)) void bulk("delete");
              }}
            >
              Entfernen
            </button>
          </>
        )}
      </div>

      {shown.map((s) => (
        <div key={s.name} style={row}>
          <input type="checkbox" checked={selected.has(s.name)} onChange={() => toggle(s.name)} aria-label={`${s.name} auswählen`} />
          <strong>{s.name}</strong>
          {s.category && <span style={tag}>{s.category}</span>}
          <span style={{ ...muted, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.url}</span>
          <button onClick={() => void act(() => removeStation(s.name), `${s.name} entfernt.`)}>Entfernen</button>
        </div>
      ))}
      {hits.length > SHOW_ADMIN && <p style={muted}>… und {hits.length - SHOW_ADMIN} weitere – Suche eingrenzen („Alle Treffer auswählen“ erfasst trotzdem alle).</p>}
      {stations.length > 0 && hits.length === 0 && <p style={muted}>Keine passenden Sender.</p>}

      <div style={{ ...row, flexWrap: "wrap", marginTop: 12 }}>
        <input placeholder="Name" value={station.name} onChange={(e) => setStation({ ...station, name: e.target.value })} />
        <input
          placeholder="Stream-Adresse oder .m3u/.pls"
          style={{ flex: 1, minWidth: 240 }}
          value={station.url}
          onChange={(e) => setStation({ ...station, url: e.target.value })}
        />
        <input
          list="music-categories"
          placeholder="Kategorie (optional)"
          value={station.category}
          onChange={(e) => setStation({ ...station, category: e.target.value })}
        />
        <button
          disabled={!station.name || !station.url}
          onClick={() =>
            void act(() => addStation(station.name, station.url, station.category), `${station.name} eingetragen.`).then(
              (ok) => ok && setStation({ name: "", url: "", category: "" }),
            )
          }
        >
          Hinzufügen
        </button>
      </div>
      <div style={{ ...row, flexWrap: "wrap" }}>
        <input
          placeholder="Sender-Liste importieren: Adresse einer .m3u/.pls (GitHub: Raw-Adresse)"
          style={{ flex: 1, minWidth: 320 }}
          value={importUrl}
          onChange={(e) => setImportUrl(e.target.value)}
        />
        <input
          list="music-categories"
          placeholder="Kategorie für alle (leer = aus der Liste)"
          value={importCategory}
          onChange={(e) => setImportCategory(e.target.value)}
        />
        <button
          disabled={!importUrl.startsWith("http")}
          onClick={() =>
            void act(() => importStations(importUrl, importCategory), (r) => (r as { message: string }).message).then(
              (ok) => ok && setImportUrl(""),
            )
          }
        >
          Importieren
        </button>
      </div>
      <p style={muted}>
        Doppelte Sender (gleiche Adresse oder gleicher Name) werden nicht angelegt. Bringt die Liste Genres mit (group-title), werden
        sie als Kategorie übernommen. Höchstens 1000 Sender pro Import.
      </p>
    </>
  );
}
