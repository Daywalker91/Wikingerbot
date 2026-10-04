import { useCallback, useEffect, useState, type CSSProperties } from "react";

import { useAuth } from "@/auth/useAuth";

import {
  applyRoles,
  checkRoles,
  getAmpKonten,
  getRolesStatus,
  refreshRoles,
  saveAmpKonten,
  type AdminLogin,
  type AmpKontenData,
  type RolesStatus,
  type SetupReport,
} from "./api";

export const route = { path: "/ampkonten", navLabel: "AMP-Konten" };

const card: CSSProperties = {
  border: "1px solid var(--wb-border)",
  borderRadius: 8,
  padding: 16,
  background: "var(--wb-surface)",
  marginBottom: 16,
};
const muted: CSSProperties = { color: "var(--wb-text-muted)", fontSize: "0.9em" };
const cell: CSSProperties = { padding: "6px 8px", borderBottom: "1px solid var(--wb-border)" };

/** Gameserver-Rollen in AMP anlegen und ihre Rechte in allen Spiel-Instanzen setzen. */
function RoleSetup({ onDone }: { onDone: () => void }) {
  const [status, setStatus] = useState<RolesStatus | null>(null);
  const [report, setReport] = useState<SetupReport | null>(null);
  const [applied, setApplied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [useAdmin, setUseAdmin] = useState(true);
  const [login, setLogin] = useState<AdminLogin>({ username: "", password: "", token: "" });

  const loadStatus = useCallback(() => {
    getRolesStatus()
      .then(setStatus)
      .catch((e: Error) => setNote(e.message));
  }, []);
  useEffect(loadStatus, [loadStatus]);

  async function run(apply: boolean) {
    if (useAdmin && (!login.username.trim() || !login.password)) {
      setNote("Benutzername und Passwort eines AMP-Super-Admins eingeben.");
      return;
    }
    if (apply && !useAdmin && !window.confirm("Hat der AMP-Benutzer des Bots gerade die Rolle „Super Admins“? Ohne sie lehnt AMP das Einrichten ab.")) return;
    setBusy(true);
    setNote(null);
    const credentials = useAdmin ? login : null;
    try {
      setReport(await (apply ? applyRoles(credentials) : checkRoles(credentials)));
      setLogin({ ...login, password: "", token: "" }); // nichts im Browser liegen lassen
      setApplied(apply);
      if (apply) {
        loadStatus();
        onDone();
      }
    } catch (error) {
      setNote((error as Error).message);
    }
    setBusy(false);
  }

  return (
    <section style={card}>
      <h2 style={{ marginTop: 0 }}>Gameserver-Rollen in AMP</h2>
      <p style={muted}>
        Der Bot legt drei Rollen an und setzt ihre Rechte am Controller (Anmelden, nur die Spiel-Instanzen) und in jeder
        Spiel-Instanz. Nie: Benutzer- und Rollenverwaltung, Audit-Log, die Instanz des Bots. Erst <strong>Prüfen</strong>{" "}
        (ändert nichts), dann <strong>Einrichten</strong>. Bei jedem neuen Gameserver erneut einrichten.
      </p>
      <div style={{ margin: "8px 0" }}>
        <label>
          <input type="radio" checked={useAdmin} onChange={() => setUseAdmin(true)} /> Mit meinem AMP-Admin-Konto anmelden
        </label>{" "}
        <label>
          <input type="radio" checked={!useAdmin} onChange={() => setUseAdmin(false)} /> Der Bot hat gerade „Super Admins“
        </label>
      </div>
      {useAdmin && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", margin: "8px 0" }}>
          <input placeholder="AMP-Benutzer" autoComplete="off" value={login.username} onChange={(e) => setLogin({ ...login, username: e.target.value })} />
          <input type="password" placeholder="Passwort" autoComplete="off" value={login.password} onChange={(e) => setLogin({ ...login, password: e.target.value })} />
          <input placeholder="2FA-Code (falls aktiv)" autoComplete="one-time-code" style={{ width: 150 }} value={login.token} onChange={(e) => setLogin({ ...login, token: e.target.value })} />
          <span style={muted}>
            Nur für diesen Vorgang – wird nicht gespeichert. Mit Zwei-Faktor kann es bei mehreren Gameservern scheitern (der Code
            gilt nur kurz); dann den anderen Weg nehmen.
          </span>
        </div>
      )}
      {status && (
        <>
          <ul style={{ margin: "8px 0", paddingLeft: 20 }}>
            {status.tiers.map((t) => (
              <li key={t.key}>
                <strong>{t.name}</strong>: {t.caps.join(", ")}
              </li>
            ))}
          </ul>
          {status.pending.length > 0 && (
            <p style={{ ...muted, color: "var(--wb-accent-strong)" }}>Noch nicht eingerichtet: {status.pending.join(", ")}</p>
          )}
          {status.done.length > 0 && <p style={muted}>Eingerichtet: {status.done.join(", ")}</p>}
        </>
      )}
      <div style={{ display: "flex", gap: 8 }}>
        <button disabled={busy} onClick={() => void run(false)}>
          Prüfen
        </button>
        <button disabled={busy} onClick={() => void run(true)}>
          Einrichten
        </button>
        {busy && <span style={muted}>läuft…</span>}
      </div>
      {note && <p>{note}</p>}
      {report && <SetupResult report={report} applied={applied} />}
    </section>
  );
}

function SetupResult({ report, applied }: { report: SetupReport; applied: boolean }) {
  const c = report.controller;
  return (
    <div style={{ marginTop: 12 }}>
      {report.errors.map((e) => (
        <p key={e} style={{ color: "var(--wb-accent-strong)" }}>
          {e}
        </p>
      ))}
      {applied && !report.errors.length && (
        <p>
          Eingerichtet – {report.changed} Rechte gesetzt
          {report.created_roles.length > 0 && `, neu angelegt: ${report.created_roles.join(", ")}`}.
        </p>
      )}
      {c.login && (
        <details>
          <summary>Controller: Anmelden {c.login.length ? "✅" : "❌ nicht gefunden"}, Spiel-Instanzen {Object.keys(c.instances ?? {}).length}</summary>
          <div style={muted}>Anmelden: {c.login.join(", ") || "–"}</div>
          {Object.entries(c.instances ?? {}).map(([name, nodes]) => (
            <div key={name} style={muted}>
              {name}: {nodes.join(", ")}
            </div>
          ))}
          {(c.other_nodes ?? []).length > 0 && (
            <details style={{ marginLeft: 16 }}>
              <summary style={muted}>Alle Controller-Rechte außerhalb der Instanzen ({c.other_nodes!.length})</summary>
              <pre style={{ ...muted, whiteSpace: "pre-wrap", fontSize: "0.8em" }}>{c.other_nodes!.join("\n")}</pre>
            </details>
          )}
          {(c.missing_instances ?? []).length > 0 && (
            <div style={{ color: "var(--wb-accent-strong)" }}>Keine „Manage“-Berechtigung gefunden für: {c.missing_instances!.join(", ")}</div>
          )}
        </details>
      )}
      {Object.entries(report.instances).map(([name, plan]) => (
        <details key={name}>
          <summary>
            {name}: {plan.error ? `❌ ${plan.error}` : Object.values(plan).some((t) => typeof t === "object" && t.missing?.length) ? "⚠️ nicht alles gefunden" : "✅"}
          </summary>
          {!plan.error &&
            Object.entries(plan).map(([tier, t]) =>
              typeof t !== "object" ? null : (
                <div key={tier} style={{ ...muted, margin: "4px 0 8px" }}>
                  <strong>{tier}</strong>
                  {t.error && <span style={{ color: "var(--wb-accent-strong)" }}> – {t.error}</span>}
                  <div>erlaubt: {t.allow.join(", ") || "–"}</div>
                  {t.missing.length > 0 && <div style={{ color: "var(--wb-accent-strong)" }}>nicht gefunden: {t.missing.join(", ")}</div>}
                </div>
              ),
            )}
        </details>
      ))}
    </div>
  );
}

export default function AmpKontenPage() {
  const { user } = useAuth();
  const [data, setData] = useState<AmpKontenData | null>(null);
  const [url, setUrl] = useState("");
  const [map, setMap] = useState<Record<string, string | null>>({});
  const [requires, setRequires] = useState("");
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    const loaded = await getAmpKonten();
    setData(loaded);
    setUrl(loaded.url);
    setMap(loaded.map);
    setRequires(loaded.requires);
  }, []);

  useEffect(() => {
    if (user?.level === "owner") load().catch((e: Error) => setNote(e.message));
  }, [user?.level, load]);

  if (user?.level !== "owner") return <main style={{ padding: 24 }}>Nur für den Owner.</main>;
  if (!data) return <main style={{ padding: 24 }}>{note ?? "Lädt…"}</main>;

  async function act(action: () => Promise<unknown>, success: (r: unknown) => string) {
    setNote(null);
    try {
      setNote(success(await action()));
      await load();
    } catch (error) {
      setNote((error as Error).message);
    }
  }

  return (
    <main style={{ padding: 24, maxWidth: 900 }}>
      <h1>AMP-Konten</h1>
      <p style={muted}>
        Mitglieder beantragen auf der Community-Seite (Einstellungen → AMP-Zugang) ein AMP-Konto. Der Bot legt es an, gibt
        ihm die AMP-Rolle ihres Rangs und schickt das Startpasswort per Discord-DM (beim ersten Login muss es geändert
        werden). Ändert sich der Rang, passt er die Rolle an; ohne Zugang wird das Konto gesperrt, nie gelöscht. Er fasst nur
        Konten an, die er selbst angelegt hat, und vergibt nie Super Admins.
      </p>
      {!data.amp_configured && <p style={card}>Der Bot hat keinen AMP-Zugang (AMP-Benutzer in AMP eintragen).</p>}
      {!data.community_enabled && <p style={card}>Die Community-Seite ist nicht angebunden (Tab Community).</p>}
      {data.error && <p style={card}>{data.error}</p>}
      {note && <p style={{ ...card, padding: "8px 12px" }}>{note}</p>}

      <section style={card}>
        <h2 style={{ marginTop: 0 }}>Einstellungen</h2>
        <label>
          Adresse des AMP-Panels für die DM
          <br />
          <input style={{ width: "100%", maxWidth: 420 }} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://amp.example.com" />
        </label>

        <div style={{ marginTop: 16 }}>
          <label>
            Voraussetzung:{" "}
            <select value={requires} onChange={(e) => setRequires(e.target.value)}>
              <option value="">– keine, nur der Rang zählt –</option>
              {data.extra_roles.map((x) => (
                <option key={x.slug} value={x.slug}>
                  Zusatzrolle „{x.name}“
                </option>
              ))}
            </select>
          </label>
          <div style={muted}>
            Mit Voraussetzung gibt es ohne diese Zusatzrolle keinen Zugang (wer sie verliert, wird gesperrt); mit ihr
            bestimmt der Rang die AMP-Rolle unten.
          </div>
        </div>

        <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 16 }}>
          <thead>
            <tr style={{ textAlign: "left" }}>
              <th style={cell}>Rang (Seite)</th>
              <th style={cell}>AMP-Rolle</th>
            </tr>
          </thead>
          <tbody>
            {data.ranks.map((r) => (
              <tr key={r.slug}>
                <td style={cell}>{r.name}</td>
                <td style={cell}>
                  <select value={map[r.slug] ?? ""} onChange={(e) => setMap({ ...map, [r.slug]: e.target.value || null })}>
                    <option value="">– kein Zugang –</option>
                    {data.roles.map((role) => (
                      <option key={role.id} value={role.id}>
                        {role.name}
                      </option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p style={muted}>
          {data.roles.length === 0
            ? "Noch keine AMP-Rollen bekannt – „Rollen neu laden“ oder dem Bot-Benutzer einmal kurz Super Admins geben und den Bot neu starten."
            : data.roles_fresh
              ? "Rollen frisch aus AMP."
              : "Gemerkte Rollenliste – neue AMP-Rollen erscheinen nach „Rollen neu laden“ (dafür braucht der Bot einmal kurz Super Admins)."}
        </p>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={() => void act(() => saveAmpKonten(url, map, requires), () => "Gespeichert.")}>Speichern</button>
          <button
            onClick={() =>
              void act(refreshRoles, (r) =>
                (r as { fresh: boolean }).fresh ? "Rollen neu geladen." : "AMP erlaubt dem Bot gerade nicht, Rollen zu lesen – gemerkte Liste bleibt.",
              )
            }
          >
            Rollen neu laden
          </button>
        </div>
      </section>

      <RoleSetup onDone={() => void load()} />

      <section style={card}>
        <h2 style={{ marginTop: 0 }}>Angelegte Konten</h2>
        {data.accounts.length === 0 && <p style={muted}>Noch keine.</p>}
        {data.accounts.map((a) => (
          <div key={a.amp_username} style={{ ...cell, display: "flex", gap: 12 }}>
            <strong style={{ minWidth: 140 }}>{a.amp_username}</strong>
            <span style={{ flex: 1 }}>{a.member}</span>
            <span style={muted}>{a.disabled ? "🔒 gesperrt" : a.roles.join(", ") || "–"}</span>
          </div>
        ))}
      </section>
    </main>
  );
}
