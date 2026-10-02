import { useCallback, useEffect, useState, type CSSProperties } from "react";

import { useAuth } from "@/auth/useAuth";

import { getAmpKonten, refreshRoles, saveAmpKonten, type AmpKontenData } from "./api";

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

export default function AmpKontenPage() {
  const { user } = useAuth();
  const [data, setData] = useState<AmpKontenData | null>(null);
  const [url, setUrl] = useState("");
  const [map, setMap] = useState<Record<string, string | null>>({});
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    const loaded = await getAmpKonten();
    setData(loaded);
    setUrl(loaded.url);
    setMap(loaded.map);
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
          <button onClick={() => void act(() => saveAmpKonten(url, map), () => "Gespeichert.")}>Speichern</button>
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
