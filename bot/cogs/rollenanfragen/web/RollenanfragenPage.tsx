import { useEffect, useState, type CSSProperties } from "react";

import { getRoleRequests, type RoleRequestsData } from "./api";

export const route = { path: "/rollenanfragen", navLabel: "Rollenanfragen" };

const card: CSSProperties = {
  border: "1px solid var(--wb-border)",
  borderRadius: 8,
  padding: 16,
  background: "var(--wb-surface)",
  marginBottom: 16,
};
const muted: CSSProperties = { color: "var(--wb-text-muted)", fontSize: "0.9em" };
const cell: CSSProperties = { padding: "6px 8px", borderBottom: "1px solid var(--wb-border)", verticalAlign: "top" };

const STATUS: Record<string, string> = { pending: "⏳ offen", approved: "✅ zugestimmt", denied: "❌ abgelehnt", cancelled: "↩️ zurückgezogen" };

/** Rollenanfragen der Seite - nur Anzeige; entschieden wird in Discord. */
export default function RollenanfragenPage() {
  const [data, setData] = useState<RoleRequestsData | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    getRoleRequests()
      .then(setData)
      .catch((e: Error) => setNote(e.message));
  }, []);

  if (!data) return <main style={{ padding: 24 }}>{note ?? "Lädt…"}</main>;

  return (
    <main style={{ padding: 24, maxWidth: 1100 }}>
      <h1>Rollenanfragen</h1>
      <p style={muted}>
        Mitglieder beantragen auf der Seite unter Einstellungen → Rolle beantragen die nächste Rangstufe oder eine Zusatzrolle. Dazu
        entsteht ein Ticket; im Mod-Log und im Ticket-Thread stehen die Knöpfe <strong>Zustimmen</strong> und{" "}
        <strong>Ablehnen</strong>. Entscheiden darf der König – bei Zusatzrollen sonst, wer ab Mod ist und die Rolle selbst hat (für
        Mitglieder bis zum eigenen Rang), bei Rängen, wer ab Mod ist und darüber steht. Nie bei der eigenen Anfrage.
      </p>
      {!data.community_enabled && <p style={card}>Die Community-Seite ist nicht angebunden (Tab Community).</p>}
      {!data.cog_loaded && <p style={card}>Der Rollenanfragen-Cog ist nicht geladen.</p>}
      {data.community_enabled && !data.modlog_set && (
        <p style={card}>Kein Mod-Log-Kanal gesetzt (Tab Moderation) – die Knöpfe erscheinen dann nur im Ticket-Thread.</p>
      )}
      {data.error && <p style={{ ...card, color: "var(--wb-accent-strong)" }}>{data.error}</p>}
      {data.requests.length === 0 && !data.error && <p style={muted}>Noch keine Anfragen.</p>}
      {data.requests.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={cell}>#</th>
              <th style={cell}>Mitglied</th>
              <th style={cell}>Beantragt</th>
              <th style={cell}>Stand</th>
              <th style={cell}>Begründung / Entscheidung</th>
            </tr>
          </thead>
          <tbody>
            {data.requests.map((r) => (
              <tr key={r.id}>
                <td style={cell}>{r.ticket_link ? <a href={r.ticket_link} target="_blank" rel="noreferrer">{r.id}</a> : r.id}</td>
                <td style={cell}>
                  {r.member} <span style={muted}>({r.rank})</span>
                </td>
                <td style={cell}>
                  {r.role} <span style={muted}>{r.kind === "extra" ? "Zusatzrolle" : "Rang"}</span>
                </td>
                <td style={cell}>
                  {STATUS[r.status] ?? r.status}
                  {r.created_at && <div style={muted}>{new Date(r.created_at).toLocaleDateString("de-DE")}</div>}
                </td>
                <td style={cell}>
                  {r.reason || "–"}
                  {r.decided_by && (
                    <div style={muted}>
                      von {r.decided_by}
                      {r.note ? `: ${r.note}` : ""}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
