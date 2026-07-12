import { useEffect, useState } from "react";

import {
  banUser,
  getEscalations,
  getModConfig,
  getModLog,
  getWarnings,
  resetEscalation,
  searchMembers,
  unbanUser,
  updateModConfig,
} from "./api";
import type { EscalationState, LadderAction, MemberSearchResult, ModConfig, ModLogEntryItem, WarningItem } from "./types";

export const route = { path: "/moderation", navLabel: "Moderation" };

const PRESET_REASONS = [
  "Spam",
  "Beleidigungen / Belästigung",
  "Wiederholter Regelverstoß",
  "Werbung / Scam",
  "Cheating / Exploits",
  "NSFW-Inhalte",
];

const LADDER_ACTIONS: LadderAction[] = ["timeout", "kick", "ban"];
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

  const [escalations, setEscalations] = useState<EscalationState[] | null>(null);
  const [resetUserId, setResetUserId] = useState("");

  const [memberQuery, setMemberQuery] = useState("");
  const [memberResults, setMemberResults] = useState<MemberSearchResult[]>([]);

  const [message, setMessage] = useState<string | null>(null);

  async function load() {
    const [modlogResult, warningsResult, config, escalationsResult] = await Promise.all([
      getModLog(),
      getWarnings(),
      getModConfig(),
      getEscalations(),
    ]);
    setModlog(modlogResult);
    setWarnings(warningsResult);
    setModConfig(config);
    setEscalations(escalationsResult);
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

  function updateLadderTier(index: number, action: LadderAction) {
    if (!modConfig) return;
    const warn_ladder = [...modConfig.warn_ladder];
    warn_ladder[index] = action;
    setModConfig({ ...modConfig, warn_ladder });
  }

  function addLadderTier() {
    if (!modConfig) return;
    setModConfig({ ...modConfig, warn_ladder: [...modConfig.warn_ladder, "timeout"] });
  }

  function removeLadderTier(index: number) {
    if (!modConfig) return;
    setModConfig({ ...modConfig, warn_ladder: modConfig.warn_ladder.filter((_, i) => i !== index) });
  }

  function moveLadderTier(index: number, direction: -1 | 1) {
    if (!modConfig) return;
    const target = index + direction;
    if (target < 0 || target >= modConfig.warn_ladder.length) return;
    const warn_ladder = [...modConfig.warn_ladder];
    [warn_ladder[index], warn_ladder[target]] = [warn_ladder[target], warn_ladder[index]];
    setModConfig({ ...modConfig, warn_ladder });
  }

  async function handleResetEscalation(userId: string) {
    if (!userId) return;
    const result = await resetEscalation(userId);
    setMessage(result.message);
    setResetUserId("");
    void load();
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
          Jede <code>/warn</code>-Verwarnung gibt Punkte (Standard: 1). Erreichen die aktiven Punkte
          eines Mitglieds die <strong>Warn-Schwelle</strong>, ruckt die Eskalation eine Stufe in der{" "}
          <strong>Eskalations-Leiter</strong> weiter (bleibt an der letzten Stufe stehen, wenn das Ende
          erreicht ist): <em>Timeout</em> (befristete Stummschaltung fuer die eingestellte{" "}
          <strong>Timeout-Dauer</strong>), <em>Ban</em> (sofortiger, dauerhafter Bann) oder{" "}
          <em>Kick (Vorschlag)</em> (schlägt einen Kick per Button im Moderations-Kanal vor, wird nicht
          automatisch ausgeführt). Timeout und Ban erzeugen zusätzlich eine Bestätigen/Aufheben-Nachricht
          in Discord. Warnpunkte verfallen automatisch nach der eingestellten Anzahl Tage - das betrifft
          nur, ob NEUE Verwarnungen erneut über die Schwelle führen, die Eskalationsstufe selbst muss
          separat zurückgesetzt werden (siehe unten).
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
              <div>Eskalations-Leiter:</div>
              {modConfig.warn_ladder.map((action, index) => (
                <div key={index} style={{ marginBottom: 4 }}>
                  <span style={{ display: "inline-block", width: 24 }}>{index + 1}.</span>
                  <select
                    value={action}
                    onChange={(e) => updateLadderTier(index, e.target.value as LadderAction)}
                    style={{ marginRight: 8 }}
                  >
                    {LADDER_ACTIONS.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                  <button onClick={() => moveLadderTier(index, -1)} disabled={index === 0}>
                    ↑
                  </button>
                  <button
                    onClick={() => moveLadderTier(index, 1)}
                    disabled={index === modConfig.warn_ladder.length - 1}
                    style={{ marginRight: 8 }}
                  >
                    ↓
                  </button>
                  <button onClick={() => removeLadderTier(index)}>Entfernen</button>
                </div>
              ))}
              <button onClick={addLadderTier}>Stufe hinzufügen</button>
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
            <div style={{ marginBottom: 8 }}>
              <label>
                Warnpunkte verfallen nach{" "}
                <input
                  type="number"
                  value={modConfig.warn_decay_days}
                  onChange={(e) => setModConfig({ ...modConfig, warn_decay_days: Number(e.target.value) })}
                  style={{ width: 80 }}
                />{" "}
                Tagen
              </label>
            </div>
            <button onClick={() => void handleSaveModConfig()}>Speichern</button>
          </div>
        )}
      </section>

      <section style={{ marginBottom: 32 }}>
        <h2>Eskalationsstufen</h2>
        <p style={{ color: "#999", fontSize: "0.9em", maxWidth: 640 }}>
          Zeigt Mitglieder, die aktuell in der Eskalations-Leiter fortgeschritten sind. Zurücksetzen
          bringt die nächste Eskalation wieder auf die erste Stufe (Warnpunkte selbst bleiben davon
          unberührt).
        </p>
        <div style={{ marginBottom: 12 }}>
          <input
            placeholder="User-ID oder Name"
            list="member-suggestions"
            value={resetUserId}
            onChange={(e) => {
              setResetUserId(e.target.value);
              setMemberQuery(e.target.value);
            }}
            style={{ marginRight: 8 }}
          />
          <button onClick={() => void handleResetEscalation(resetUserId)}>Zurücksetzen</button>
        </div>
        {escalations === null && <p>Lädt…</p>}
        {escalations !== null && escalations.length === 0 && <p>Keine aktiven Eskalationsstufen.</p>}
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {escalations?.map((state) => (
            <div
              key={state.user_id}
              style={{ border: "1px solid #444", borderRadius: 8, padding: "8px 12px" }}
            >
              Nutzer {state.user_id} — Stufe {state.tier + 1}
              <button
                onClick={() => void handleResetEscalation(String(state.user_id))}
                style={{ marginLeft: 12 }}
              >
                Zurücksetzen
              </button>
            </div>
          ))}
        </div>
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
