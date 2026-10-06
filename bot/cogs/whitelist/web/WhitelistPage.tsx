import { useEffect, useState } from "react";

import {
  approveGroup,
  approveRequest,
  denyGroup,
  denyRequest,
  getGroupRequests,
  getRequests,
  revokeGroup,
  revokeRequest,
  type GroupRequestItem,
} from "./api";
import type { WhitelistRequestItem, WhitelistStatus } from "./types";

export const route = { path: "/whitelist", navLabel: "Whitelist" };

const STATUS_OPTIONS: WhitelistStatus[] = ["pending", "approved", "denied", "revoked"];
const STATUS_LABELS: Record<WhitelistStatus, string> = {
  pending: "Offen",
  approved: "Genehmigt",
  denied: "Abgelehnt",
  revoked: "Entzogen",
};

export default function WhitelistPage() {
  const [status, setStatus] = useState<WhitelistStatus>("pending");
  const [requests, setRequests] = useState<WhitelistRequestItem[] | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [groups, setGroups] = useState<GroupRequestItem[] | null>(null);

  async function load(targetStatus: WhitelistStatus) {
    setRequests(await getRequests(targetStatus));
    setGroups(await getGroupRequests(targetStatus).catch(() => []));
  }

  async function groupAction(action: () => Promise<{ message: string }>) {
    try {
      setMessage((await action()).message);
    } catch (error) {
      setMessage((error as Error).message);
    }
    void load(status);
  }

  useEffect(() => {
    void load(status);
  }, [status]);

  async function handleApprove(id: number) {
    const result = await approveRequest(id);
    setMessage(result.message);
    void load(status);
  }

  async function handleRevoke(id: number) {
    const reason = window.prompt("Freigabe entziehen – Begründung (optional, bekommt das Mitglied per DM):");
    if (reason === null) return;
    try {
      setMessage((await revokeRequest(id, reason || undefined)).message);
    } catch (error) {
      setMessage((error as Error).message);
    }
    void load(status);
  }

  async function handleDeny(id: number) {
    const reason = window.prompt("Begründung (optional):") ?? undefined;
    const result = await denyRequest(id, reason);
    setMessage(result.message);
    void load(status);
  }

  return (
    <main style={{ padding: 24 }}>
      <h1>Whitelist</h1>

      <div style={{ marginBottom: 16 }}>
        {STATUS_OPTIONS.map((option) => (
          <button
            key={option}
            onClick={() => setStatus(option)}
            disabled={option === status}
            style={{ marginRight: 8 }}
          >
            {STATUS_LABELS[option]}
          </button>
        ))}
      </div>

      {message && <p>{message}</p>}
      {requests === null && <p>Lädt…</p>}
      {requests !== null && requests.length === 0 && <p>Keine Anfragen mit Status „{STATUS_LABELS[status]}“.</p>}

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {requests?.map((request) => (
          <div key={request.id} style={{ border: "1px solid #444", borderRadius: 8, padding: "12px 16px" }}>
            <strong>#{request.id}</strong> {request.ign} · {request.server_name}
            <div style={{ color: "#999", fontSize: "0.9em" }}>
              {new Date(request.created_at).toLocaleString()}
            </div>
            {request.status === "pending" && (
              <div style={{ marginTop: 8 }}>
                <button onClick={() => void handleApprove(request.id)} style={{ marginRight: 8 }}>
                  Annehmen
                </button>
                <button onClick={() => void handleDeny(request.id)}>Ablehnen</button>
              </div>
            )}
            {request.status === "approved" && (
              <div style={{ marginTop: 8 }}>
                <button onClick={() => void handleRevoke(request.id)}>Entziehen</button>
              </div>
            )}
          </div>
        ))}
      </div>

      <h2 style={{ marginTop: 32 }}>Gruppen-Rollen</h2>
      <p style={{ color: "#999", fontSize: "0.9em" }}>
        Anfragen über Panel-Knöpfe mit Bestätigung (z.B. Spielgruppen) – wie eine Whitelist, nur ohne Gameserver.
      </p>
      {groups !== null && groups.length === 0 && <p>Keine Gruppen-Anfragen mit Status „{STATUS_LABELS[status]}“.</p>}
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {groups?.map((group) => (
          <div key={group.id} style={{ border: "1px solid #444", borderRadius: 8, padding: "12px 16px" }}>
            <strong>#{group.id}</strong> {group.user_name ?? group.user_id} · @{group.role_name}
            <div style={{ color: "#999", fontSize: "0.9em" }}>
              {new Date(group.created_at).toLocaleString()}
              {group.note ? ` · ${group.note}` : ""}
            </div>
            {group.status === "pending" && (
              <div style={{ marginTop: 8 }}>
                <button onClick={() => void groupAction(() => approveGroup(group.id))} style={{ marginRight: 8 }}>
                  Annehmen
                </button>
                <button
                  onClick={() => {
                    const reason = window.prompt("Begründung (bekommt das Mitglied per DM):");
                    if (reason !== null) void groupAction(() => denyGroup(group.id, reason || undefined));
                  }}
                >
                  Ablehnen
                </button>
              </div>
            )}
            {group.status === "approved" && (
              <div style={{ marginTop: 8 }}>
                <button
                  onClick={() => {
                    const reason = window.prompt("Rolle entziehen – Begründung (optional, bekommt das Mitglied per DM):");
                    if (reason !== null) void groupAction(() => revokeGroup(group.id, reason || undefined));
                  }}
                >
                  Entziehen
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </main>
  );
}
