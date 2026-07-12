import { useEffect, useState } from "react";

import { banUser, getModConfig, getModLog, getWarnings, searchMembers, unbanUser, updateModConfig } from "./api";
import type { MemberSearchResult, ModConfig, ModLogEntryItem, WarningItem } from "./types";

export const route = { path: "/moderation", navLabel: "Moderation" };

const PRESET_REASONS = [
  "Spam",
  "Beleidigungen / Belästigung",
  "Wiederholter Regelverstoß",
  "Werbung / Scam",
  "Cheating / Exploits",
  "NSFW-Inhalte",
];

const WARN_ACTIONS: ModConfig["warn_action"][] = ["timeout", "ban", "kick"];
const MEMBER_SEARCH_DEBOUNCE_MS = 300;

export default function ModerationPage() {
  const [modlog, setModlog] = useState<ModLogEntryItem[] | null>(null);
  const [warnings, setWarnings] = useState<WarningItem[] | null>(null);
  const [unbanUserId, setUnbanUserId] = useState("");
  const [unbanReason, setUnbanReason] = useState("");

  const [banUserId, setBanUserId] = useState("");
  const [banReason, setBanReason] = useState("");
  const [banDeleteDays, setBanDeleteDays] = useState(0);

  const [modConfig, setModConfig] = useState<ModConfig | null>(null);

  const [memberQuery, setMemberQuery] = useState("");
  const [memberResults, setMemberResults] = useState<MemberSearchResult[]>([]);

  const [message, setMessage] = useState<string | null>(null);

  async function load() {
    const [modlogResult, warningsResult, config] = await Promise.all([
      getModLog(),
      getWarnings(),
      getModConfig(),
    ]);
    setModlog(modlogResult);
    setWarnings(warningsResult);
    setModConfig(config);
  }

  useEffect(() => {
    void load();
  }, []);

  // Autocomplete fuers User-ID-Feld in Bann/Entbannen: per Name ODER direkt per
  // ID suchbar, siehe bot/cogs/moderation/api.py:search_members. Debounced,
  // damit nicht bei jedem Tastendruck ein Discord-REST-Call rausgeht.
  useEffect(() => {
    if (memberQuery.trim().length < 2) {
      setMemberResults([]);
      return;
    }
    const timeout = setTimeout(() => {
      void searchMembers(memberQuery).then(setMemberResults);
    }, MEMBER_SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timeout);
  }, [memberQuery]);

  async function handleSaveModConfig() {
    if (!modConfig) return;
    const result = await updateModConfig(modConfig);
    setModConfig(result);
    setMessage("Gespeichert.");
  }

  async function handleUnban() {
    if (!unbanUserId) return;
    const result = await unbanUser(unbanUserId, unbanReason || "Kein Grund angegeben");
    setMessage(result.message);
    setUnbanUserId("");
    setUnbanReason("");
    void load();
  }

  async function handleBan() {
    if (!banUserId || !banReason) return;
    const result = await banUser(banUserId, banReason, banDeleteDays);
    setMessage(result.message);
    setBanUserId("");
    setBanReason("");
    setBanDeleteDays(0);
    void load();
  }

  return (
    <main style={{ padding: 24 }}>
      <h1>Moderation</h1>
      {message && <p>{message}</p>}

      <datalist id="member-suggestions">
        {memberResults.map((member) => (
          <option key={member.id} value={member.id}>
            {member.display_name} (@{member.username})
          </option>
        ))}
      </datalist>

      <section style={{ marginBottom: 32 }}>
        <h2>Bannen</h2>
        <div style={{ marginBottom: 8 }}>
          <input
            placeholder="User-ID oder Name"
            list="member-suggestions"
            value={banUserId}
            onChange={(e) => {
              setBanUserId(e.target.value);
              setMemberQuery(e.target.value);
            }}
            style={{ marginRight: 8 }}
          />
          <select
            value=""
            onChange={(e) => e.target.value && setBanReason(e.target.value)}
            style={{ marginRight: 8 }}
          >
            <option value="">Vorgefertigter Grund…</option>
            {PRESET_REASONS.map((reason) => (
              <option key={reason} value={reason}>
                {reason}
              </option>
            ))}
          </select>
          <input
            placeholder="Begründung"
            value={banReason}
            onChange={(e) => setBanReason(e.target.value)}
            style={{ marginRight: 8, width: 220 }}
          />
        </div>
        <div style={{ marginBottom: 8 }}>
          <label>
            Nachrichten der letzten{" "}
            <input
              type="number"
              min={0}
              max={7}
              value={banDeleteDays}
              onChange={(e) => setBanDeleteDays(Number(e.target.value))}
              style={{ width: 50 }}
            />{" "}
            Tage löschen
          </label>
        </div>
        <button onClick={() => void handleBan()}>Bannen</button>
      </section>

      <section style={{ marginBottom: 32 }}>
        <h2>Bann aufheben</h2>
        <input
          placeholder="User-ID oder Name"
          list="member-suggestions"
          value={unbanUserId}
          onChange={(e) => {
            setUnbanUserId(e.target.value);
            setMemberQuery(e.target.value);
          }}
          style={{ marginRight: 8 }}
        />
        <input
          placeholder="Begründung"
          value={unbanReason}
          onChange={(e) => setUnbanReason(e.target.value)}
          style={{ marginRight: 8 }}
        />
        <button onClick={() => void handleUnban()}>Entbannen</button>
      </section>

      <section style={{ marginBottom: 32 }}>
        <h2>Warn-Konfiguration</h2>
        <p style={{ color: "#999", fontSize: "0.9em", maxWidth: 640 }}>
          Jede <code>/warn</code>-Verwarnung gibt Punkte (Standard: 1). Erreichen die aktiven
          Punkte eines Mitglieds die <strong>Warn-Schwelle</strong>, wird automatisch die{" "}
          <strong>Eskalations-Aktion</strong> ausgelöst: <em>Timeout</em> (befristete Stummschaltung
          für die unten gesetzte <strong>Timeout-Dauer</strong>), <em>Ban</em> (sofortiger,
          dauerhafter Bann) oder <em>Kick (Vorschlag)</em> (schlägt einen Kick per Button im
          Moderations-Kanal vor, wird nicht automatisch ausgeführt). Timeout und Ban erzeugen dabei
          zusätzlich eine Bestätigen/Aufheben-Nachricht in Discord, falls ein Mod die automatische
          Aktion rückgängig machen möchte.
        </p>
        {modConfig === null && <p>Lädt…</p>}
        {modConfig !== null && (
          <div>
            <div style={{ marginBottom: 8 }}>
              <label>
                Warn-Schwelle:{" "}
                <input
                  type="number"
                  value={modConfig.warn_threshold}
                  onChange={(e) => setModConfig({ ...modConfig, warn_threshold: Number(e.target.value) })}
                  style={{ width: 80 }}
                />
              </label>
            </div>
            <div style={{ marginBottom: 8 }}>
              <label>
                Eskalations-Aktion:{" "}
                <select
                  value={modConfig.warn_action}
                  onChange={(e) =>
                    setModConfig({ ...modConfig, warn_action: e.target.value as ModConfig["warn_action"] })
                  }
                >
                  {WARN_ACTIONS.map((action) => (
                    <option key={action} value={action}>
                      {action}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div style={{ marginBottom: 8 }}>
              <label>
                Timeout-Dauer (Minuten):{" "}
                <input
                  type="number"
                  value={modConfig.warn_timeout_minutes}
                  onChange={(e) =>
                    setModConfig({ ...modConfig, warn_timeout_minutes: Number(e.target.value) })
                  }
                  style={{ width: 80 }}
                />
              </label>
            </div>
            <button onClick={() => void handleSaveModConfig()}>Speichern</button>
          </div>
        )}
      </section>

      <section style={{ marginBottom: 32 }}>
        <h2>ModLog</h2>
        {modlog === null && <p>Lädt…</p>}
        {modlog !== null && modlog.length === 0 && <p>Keine Einträge.</p>}
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {modlog?.map((entry) => (
            <div key={entry.id} style={{ border: "1px solid #444", borderRadius: 8, padding: "8px 12px" }}>
              <strong>{entry.action}</strong> — Nutzer {entry.user_id} von Mod {entry.mod_id}
              <div style={{ color: "#999", fontSize: "0.9em" }}>
                {new Date(entry.created_at).toLocaleString()} · {entry.reason ?? "-"}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2>Aktive Verwarnungen</h2>
        {warnings === null && <p>Lädt…</p>}
        {warnings !== null && warnings.length === 0 && <p>Keine aktiven Verwarnungen.</p>}
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {warnings?.map((warning) => (
            <div key={warning.id} style={{ border: "1px solid #444", borderRadius: 8, padding: "8px 12px" }}>
              Nutzer {warning.user_id} — {warning.points} Punkt(e) von Mod {warning.mod_id}
              <div style={{ color: "#999", fontSize: "0.9em" }}>
                {new Date(warning.created_at).toLocaleString()} · {warning.reason ?? "-"}
              </div>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
