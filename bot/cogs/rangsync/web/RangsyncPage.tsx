import { useCallback, useEffect, useState, type CSSProperties } from "react";

import { useAuth } from "@/auth/useAuth";

import { getRangsync, saveRangsync, syncAll, type Direction, type RangsyncData, type RankRow } from "./api";

export const route = { path: "/rangsync", navLabel: "Rang-Sync" };

const card: CSSProperties = {
  border: "1px solid var(--wb-border)",
  borderRadius: 8,
  padding: 16,
  background: "var(--wb-surface)",
  marginBottom: 16,
};
const muted: CSSProperties = { color: "var(--wb-text-muted)", fontSize: "0.9em" };
const cell: CSSProperties = { padding: "6px 8px", borderBottom: "1px solid var(--wb-border)", verticalAlign: "middle" };

const DIRECTION_LABELS: Record<Direction, string> = {
  both: "beide Richtungen",
  to_site: "nur Discord → Seite",
  to_discord: "nur Seite → Discord",
  off: "aus",
};

export default function RangsyncPage() {
  const { user } = useAuth();
  const [data, setData] = useState<RangsyncData | null>(null);
  const [ranks, setRanks] = useState<RankRow[]>([]);
  const [enabled, setEnabled] = useState(false);
  const [owner, setOwner] = useState<number | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    const loaded = await getRangsync();
    setData(loaded);
    // Vorschlag (gleichnamige Discord-Rolle) uebernehmen, solange nichts gewaehlt ist
    setRanks(loaded.ranks.map((r) => ({ ...r, role_id: r.role_id ?? (r.is_king ? null : r.suggested_role_id) })));
    setEnabled(loaded.enabled);
    setOwner(loaded.ticket_owner);
  }, []);

  useEffect(() => {
    if (user?.level === "owner") load().catch((e: Error) => setNote(e.message));
  }, [user?.level, load]);

  if (user?.level !== "owner") return <main style={{ padding: 24 }}>Nur für den Owner.</main>;
  if (!data) return <main style={{ padding: 24 }}>{note ?? "Lädt…"}</main>;

  const setRank = (slug: string, change: Partial<RankRow>) =>
    setRanks(ranks.map((r) => (r.slug === slug ? { ...r, ...change } : r)));

  async function act(action: () => Promise<unknown>, success: (r: unknown) => string) {
    setNote(null);
    try {
      setNote(success(await action()));
      await load();
    } catch (error) {
      setNote((error as Error).message);
    }
  }

  const save = () =>
    act(
      () =>
        saveRangsync({
          enabled,
          ticket_owner: owner,
          ranks: Object.fromEntries(ranks.map((r) => [r.slug, { role_id: r.role_id, direction: r.direction }])),
        }),
      () => "Gespeichert.",
    );

  return (
    <main style={{ padding: 24, maxWidth: 960 }}>
      <h1>Rang-Sync</h1>
      <p style={muted}>
        Hält die Ränge der Community-Seite und die Discord-Rollen verknüpfter Mitglieder gleich. Der König wird nie
        automatisch vergeben oder geändert. Weichen die Ränge beim Verknüpfen ab, eröffnet der Bot ein Ticket statt etwas zu
        ändern; ein Discord-Bann eines verknüpften Mitglieds wird ebenfalls als Ticket gemeldet. Wer Discord verlässt,
        behält seinen Rang.
      </p>
      {!data.community_enabled && (
        <p style={{ ...card, borderColor: "var(--wb-border-strong)" }}>Die Community-Seite ist nicht angebunden (Tab Community).</p>
      )}
      {data.error && <p style={card}>{data.error}</p>}
      {note && <p style={{ ...card, padding: "8px 12px" }}>{note}</p>}

      <section style={card}>
        <label>
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> <strong>Rang-Sync aktiv</strong>
        </label>
        <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 12 }}>
          <thead>
            <tr style={{ textAlign: "left" }}>
              <th style={cell}>Rang (Seite)</th>
              <th style={cell}>Discord-Rolle</th>
              <th style={cell}>Richtung</th>
            </tr>
          </thead>
          <tbody>
            {ranks.map((r) => {
              const role = data.roles.find((x) => x.id === r.role_id);
              return (
                <tr key={r.slug}>
                  <td style={cell}>{r.name}</td>
                  <td style={cell}>
                    <select value={r.role_id ?? ""} disabled={r.is_king} onChange={(e) => setRank(r.slug, { role_id: e.target.value || null })}>
                      <option value="">– keine (@everyone) –</option>
                      {data.roles.map((x) => (
                        <option key={x.id} value={x.id}>
                          @{x.name}
                        </option>
                      ))}
                    </select>
                    {role?.above_bot && (
                      <div style={{ ...muted, color: "var(--wb-accent-strong)" }}>liegt über der Bot-Rolle – kann der Bot nicht vergeben</div>
                    )}
                  </td>
                  <td style={cell}>
                    {r.is_king ? (
                      <span style={muted}>nur von Hand</span>
                    ) : (
                      <select value={r.direction} onChange={(e) => setRank(r.slug, { direction: e.target.value as Direction })}>
                        {(Object.keys(DIRECTION_LABELS) as Direction[]).map((d) => (
                          <option key={d} value={d}>
                            {DIRECTION_LABELS[d]}
                          </option>
                        ))}
                      </select>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p style={muted}>Vorbelegt mit gleichnamigen Discord-Rollen (Member, Mod, Admin), falls vorhanden – bitte prüfen und speichern.</p>

        <div style={{ margin: "12px 0" }}>
          System-Tickets (z.B. Discord-Bann) eröffnen im Namen von:{" "}
          <select value={owner ?? ""} onChange={(e) => setOwner(e.target.value ? Number(e.target.value) : null)}>
            <option value="">– automatisch (erster König) –</option>
            {data.owners.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        </div>
        <button onClick={() => void save()}>Speichern</button>
      </section>

      <section style={card}>
        <h2 style={{ marginTop: 0 }}>Einmal alles abgleichen</h2>
        <p style={muted}>
          Setzt bei allen verknüpften Mitgliedern die Discord-Rollen nach ihrem Rang auf der Seite (nur Ränge mit Richtung
          „beide“ oder „nur Seite → Discord“).
        </p>
        <button
          disabled={!data.enabled}
          onClick={() =>
            void act(syncAll, (r) =>
              Object.entries((r as { result: Record<string, number> }).result)
                .map(([k, v]) => `${k}: ${v}`)
                .join(" · "),
            )
          }
        >
          Jetzt abgleichen
        </button>
      </section>
    </main>
  );
}
