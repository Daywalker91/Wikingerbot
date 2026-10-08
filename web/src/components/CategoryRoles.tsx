import { useEffect, useState, type CSSProperties } from "react";

import { apiFetch } from "@/api/client";

/** Kategorien der Community-Seite (News & Events) -> Discord-Rollen zum Anpingen.
 *  Eine gemeinsame Zuordnung: im Tab News und im Tab Events dieselbe. */
export interface SiteCategory {
  id: number;
  name: string;
  role_ids: string[];
}

interface Props {
  /** "/news" oder "/events" - beide speichern dieselbe Zuordnung */
  apiBase: string;
  categories: SiteCategory[];
  error: string | null;
  roles: { id: string; name: string }[];
  onSaved: (message: string) => void;
}

const card: CSSProperties = {
  border: "1px solid var(--wb-border)",
  borderRadius: 8,
  padding: 16,
  background: "var(--wb-surface)",
  marginBottom: 16,
};
const muted: CSSProperties = { color: "var(--wb-text-muted)", fontSize: "0.9em" };
const chip: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  border: "1px solid var(--wb-border)",
  borderRadius: 12,
  padding: "2px 8px",
};

export default function CategoryRoles({ apiBase, categories, error, roles, onSaved }: Props) {
  const [mapping, setMapping] = useState<Record<number, string[]>>({});

  useEffect(() => {
    setMapping(Object.fromEntries(categories.map((c) => [c.id, c.role_ids])));
  }, [categories]);

  const roleName = (id: string) => roles.find((r) => r.id === id)?.name ?? "gelöschte Rolle";

  async function save() {
    try {
      await apiFetch(`${apiBase}/categories`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ roles: mapping }),
      });
      onSaved("Kategorie-Rollen gespeichert.");
    } catch (e) {
      onSaved((e as Error).message);
    }
  }

  return (
    <section style={card}>
      <h2 style={{ marginTop: 0 }}>Rollen je Kategorie</h2>
      <p style={muted}>
        Kategorien legst du auf der Seite an (Verwaltung → Kategorien) und wählst sie beim Schreiben einer News bzw. eines
        Events. Beim ersten Posten pingt der Bot alle Rollen der gewählten Kategorien. Ohne Kategorie mit Rollen gilt die
        Rolle oben. Die Zuordnung gilt für News und Events.
      </p>
      {error && <p style={muted}>{error}</p>}
      {!error && categories.length === 0 && <p style={muted}>Auf der Seite gibt es noch keine Kategorien.</p>}
      {categories.map((c) => {
        const chosen = mapping[c.id] ?? [];
        return (
          <div key={c.id} style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", margin: "8px 0" }}>
            <strong style={{ minWidth: 120 }}>{c.name}</strong>
            {chosen.map((id) => (
              <span key={id} style={chip}>
                @{roleName(id)}
                <button
                  aria-label="Entfernen"
                  style={{ border: "none", background: "none", cursor: "pointer", padding: 0 }}
                  onClick={() => setMapping({ ...mapping, [c.id]: chosen.filter((r) => r !== id) })}
                >
                  ✕
                </button>
              </span>
            ))}
            <select
              value=""
              onChange={(e) => e.target.value && setMapping({ ...mapping, [c.id]: [...chosen, e.target.value] })}
            >
              <option value="">+ Rolle</option>
              {roles
                .filter((r) => !chosen.includes(r.id))
                .map((r) => (
                  <option key={r.id} value={r.id}>
                    @{r.name}
                  </option>
                ))}
            </select>
          </div>
        );
      })}
      {categories.length > 0 && <button onClick={() => void save()}>Speichern</button>}
    </section>
  );
}
