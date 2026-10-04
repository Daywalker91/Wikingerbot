import { useEffect, useState } from "react";

import { addGuildRole, changeCog, getCogsStatus, getDiscordRoles, getGuildRoles, removeGuildRole } from "./api";
import type { CogsStatus, DiscordRoleItem, GuildRoleItem, PermissionLevel } from "./types";

export const route = { path: "/settings", navLabel: "Einstellungen" };

const LEVELS: PermissionLevel[] = ["member", "mod", "admin", "owner"];

export default function SettingsPage() {
  const [discordRoles, setDiscordRoles] = useState<DiscordRoleItem[]>([]);
  const [guildRoles, setGuildRoles] = useState<GuildRoleItem[]>([]);
  const [newRoleId, setNewRoleId] = useState("");
  const [newLevel, setNewLevel] = useState<PermissionLevel>("mod");

  const [cogsStatus, setCogsStatus] = useState<CogsStatus | null>(null);
  const [cogNote, setCogNote] = useState<string | null>(null);

  async function cogAction(name: string, action: "load" | "unload" | "reload") {
    setCogNote(null);
    try {
      setCogNote((await changeCog(name, action)).message);
    } catch (error) {
      setCogNote((error as Error).message);
    }
    setCogsStatus(await getCogsStatus());
  }

  async function load() {
    const [roles, guildRoleList, cogs] = await Promise.all([
      getDiscordRoles(),
      getGuildRoles(),
      getCogsStatus(),
    ]);
    setDiscordRoles(roles);
    setGuildRoles(guildRoleList);
    setCogsStatus(cogs);
    if (roles.length > 0 && !newRoleId) {
      setNewRoleId(roles[0].id);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function roleName(discordRoleId: string): string {
    return discordRoles.find((r) => r.id === discordRoleId)?.name ?? `Rolle ${discordRoleId}`;
  }

  async function handleAddRole() {
    if (!newRoleId) return;
    await addGuildRole(newRoleId, newLevel);
    void load();
  }

  async function handleRemoveRole(id: number) {
    await removeGuildRole(id);
    void load();
  }

  return (
    <main style={{ padding: 24 }}>
      <h1>Einstellungen</h1>

      <section>
        <h2>Rollen-Zuordnung</h2>
        <p style={{ color: "#999", fontSize: "0.9em" }}>
          Ordnet Discord-Rollen ein Berechtigungslevel zu (member/mod/admin/owner).
        </p>

        <div style={{ marginBottom: 12 }}>
          <select value={newRoleId} onChange={(e) => setNewRoleId(e.target.value)} style={{ marginRight: 8 }}>
            {discordRoles.map((role) => (
              <option key={role.id} value={role.id}>
                {role.name}
              </option>
            ))}
          </select>
          <select
            value={newLevel}
            onChange={(e) => setNewLevel(e.target.value as PermissionLevel)}
            style={{ marginRight: 8 }}
          >
            {LEVELS.map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </select>
          <button onClick={() => void handleAddRole()}>Hinzufügen</button>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {guildRoles.length === 0 && <p>Keine Rollen-Zuordnungen.</p>}
          {guildRoles.map((role) => (
            <div key={role.id} style={{ border: "1px solid #444", borderRadius: 8, padding: "8px 12px" }}>
              {roleName(role.discord_role_id)} → <strong>{role.level}</strong>
              <button onClick={() => void handleRemoveRole(role.id)} style={{ marginLeft: 12 }}>
                Entfernen
              </button>
            </div>
          ))}
        </div>
      </section>

      <section style={{ marginTop: 32 }}>
        <h2>Cogs</h2>
        <p style={{ color: "#999", fontSize: "0.9em", maxWidth: 640 }}>
          Ein entladener Cog ist sofort aus – seine Befehle und Aufgaben ruhen, bis er wieder geladen wird.
          Dasselbe geht in Discord mit <code>/bot cog load|unload|reload</code>. Den Cog <code>admin</code> kann
          man nicht entladen, sonst gäbe es keinen Weg zurück.
        </p>
        {cogNote && <p>{cogNote}</p>}
        {cogsStatus === null && <p>Lädt…</p>}
        {cogsStatus !== null && (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {cogsStatus.available.map((name) => {
              const isLoaded = cogsStatus.loaded.includes(name);
              return (
                <div key={name}>
                  <span
                    style={{
                      display: "inline-block",
                      width: 10,
                      height: 10,
                      borderRadius: "50%",
                      marginRight: 8,
                      background: isLoaded ? "#4caf50" : "#777",
                    }}
                  />
                  <span style={{ display: "inline-block", minWidth: 140 }}>{name}</span>
                  {isLoaded ? (
                    <>
                      <button onClick={() => void cogAction(name, "reload")} style={{ marginRight: 6 }}>
                        Neu laden
                      </button>
                      {name !== "admin" && <button onClick={() => void cogAction(name, "unload")}>Entladen</button>}
                    </>
                  ) : (
                    <button onClick={() => void cogAction(name, "load")}>Laden</button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>
    </main>
  );
}
