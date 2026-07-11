import type { ServerStatus } from "./types";

export function ServerCard({ server }: { server: ServerStatus }) {
  return (
    <div style={{ border: "1px solid #444", borderRadius: 8, padding: "12px 16px" }}>
      <strong>{server.display_name}</strong> ({server.instance_name})
      <div>
        {server.reachable ? (
          <>
            {server.state}
            {server.players && ` · Spieler: ${server.players[0]}/${server.players[1]}`}
            {server.uptime && ` · Uptime: ${server.uptime}`}
          </>
        ) : (
          <span style={{ color: "#e74c3c" }}>Nicht erreichbar</span>
        )}
      </div>
      <div style={{ color: "#999", fontSize: "0.9em" }}>Verbinden: {server.host}</div>
    </div>
  );
}
