import { useEffect, useState } from "react";

import { addGuildRole, getDiscordRoles, getGuildRoles, removeGuildRole } from "./api";
import type { DiscordRoleItem, GuildRoleItem, PermissionLevel } from "./types";

export const route = { path: "/settings", navLabel: "Einstellungen" };

const LEVELS: PermissionLevel[] = ["member", "mod", "admin", "owner"];

export default function SettingsPage() {
  const [discordRoles, setDiscordRoles] = useState<DiscordRoleItem[]>([]);
  const [guildRoles, setGuildRoles] = useState<GuildRoleItem[]>([]);
  const [newRoleId, setNewRoleId] = useState("");
  const [newLevel, setNewLevel] = useState<PermissionLevel>("mod");

  async function load() {
    const [roles, guildRoleList] = await Promise.all([getDiscordRoles(), getGuildRoles()]);
    setDiscordRoles(roles);
    setGuildRoles(guildRoleList);
    if (roles.length > 0 && !newRoleId) {
      setNewRoleId(String(roles[0].id));
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function roleName(discordRoleId: number): string {
    return discordRoles.find((r) => r.id === discordRoleId)?.name ?? `Rolle ${discordRoleId}`;
  }

  async function handleAddRole() {
    if (!newRoleId) return;
    await addGuildRole(Number(newRoleId), newLevel);
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
    </main>
  );
}
