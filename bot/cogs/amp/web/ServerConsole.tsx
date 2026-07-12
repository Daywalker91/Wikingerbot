import { useEffect, useRef, useState } from "react";

import { getConsole, sendConsoleCommand } from "./api";
import type { ConsoleLineItem } from "./types";

const POLL_INTERVAL_MS = 3_000;
const MAX_LINES = 200;

export function ServerConsole({ serverId }: { serverId: number }) {
  const [lines, setLines] = useState<ConsoleLineItem[]>([]);
  const [command, setCommand] = useState("");
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      const newLines = await getConsole(serverId);
      if (cancelled || newLines.length === 0) return;
      setLines((prev) => [...prev, ...newLines].slice(-MAX_LINES));
    }

    void poll();
    const interval = setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [serverId]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [lines]);

  async function handleSend() {
    if (!command.trim()) return;
    await sendConsoleCommand(serverId, command);
    setCommand("");
  }

  return (
    <div style={{ marginTop: 12 }}>
      <div
        ref={logRef}
        style={{
          background: "#111",
          color: "#ddd",
          fontFamily: "monospace",
          fontSize: "0.85em",
          padding: 8,
          height: 220,
          overflowY: "auto",
          borderRadius: 4,
        }}
      >
        {lines.length === 0 && <div style={{ color: "#777" }}>Keine neuen Konsolenzeilen.</div>}
        {lines.map((line, i) => (
          <div key={i}>
            [{line.source}] {line.contents}
          </div>
        ))}
      </div>
      <div style={{ marginTop: 8 }}>
        <input
          value={command}
          onChange={(e) => setCommand(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void handleSend()}
          placeholder="Konsolenbefehl"
          style={{ marginRight: 8, width: 300 }}
        />
        <button onClick={() => void handleSend()}>Senden</button>
      </div>
    </div>
  );
}
