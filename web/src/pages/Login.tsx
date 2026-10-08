import { useEffect, useState } from "react";

import { apiFetch, loginUrl } from "@/api/client";

interface Guild {
  id: string;
  name: string;
}

// Hinweise, wenn die Anmeldung zurueckspringt (/login?error=...)
const LOGIN_ERRORS: Record<string, string> = {
  not_member: "Du bist nicht auf diesem Discord-Server – anmelden können sich nur Mitglieder.",
  denied: "Die Anmeldung bei Discord wurde abgebrochen.",
  failed: "Die Anmeldung bei Discord hat nicht geklappt – bitte nochmal versuchen.",
};

const REMEMBER_KEY = "wb-remember-login";

function storedRemember(): boolean {
  try {
    return window.localStorage.getItem(REMEMBER_KEY) === "1";
  } catch {
    return false;
  }
}

export default function Login() {
  const [guilds, setGuilds] = useState<Guild[] | null>(null);
  const [remember, setRemember] = useState(storedRemember);
  const errorCode = new URLSearchParams(window.location.search).get("error");
  const error = errorCode ? (LOGIN_ERRORS[errorCode] ?? LOGIN_ERRORS.failed) : null;

  useEffect(() => {
    // Die Server liefert der laufende Bot selbst - nur lokal ohne Bot greift
    // notfalls VITE_DISCORD_GUILD_ID.
    const fallback = import.meta.env.VITE_DISCORD_GUILD_ID;
    apiFetch<Guild[]>("/auth/guilds")
      .then((list) => setGuilds(list.length || !fallback ? list : [{ id: fallback, name: "Discord-Server" }]))
      .catch(() => setGuilds(fallback ? [{ id: fallback, name: "Discord-Server" }] : []));
  }, []);

  function handleLogin(guildId: string) {
    // Volle Seiten-Navigation (kein fetch!) - der Login-Endpunkt leitet zu
    // Discords eigener Domain weiter, das muss die SPA verlassen.
    try {
      window.localStorage.setItem(REMEMBER_KEY, remember ? "1" : "0");
    } catch {
      // ohne Speicher: Haken gilt nur fuer diese Anmeldung
    }
    window.location.href = loginUrl(guildId, remember);
  }

  return (
    <main style={{ display: "flex", height: "100vh", alignItems: "center", justifyContent: "center" }}>
      <div style={{ textAlign: "center" }}>
        <h1>WikingerBot</h1>
        {error && <p style={{ color: "var(--wb-accent-strong)" }}>{error}</p>}
        {guilds === null && <p>Lade …</p>}
        {guilds?.length === 0 && <p>Der Bot ist noch auf keinem Discord-Server.</p>}
        {guilds?.length === 1 && <button onClick={() => handleLogin(guilds[0].id)}>Mit Discord anmelden</button>}
        {guilds && guilds.length > 1 &&
          guilds.map((guild) => (
            <p key={guild.id}>
              <button onClick={() => handleLogin(guild.id)}>Bei „{guild.name}“ anmelden</button>
            </p>
          ))}
        {guilds && guilds.length > 0 && (
          <p>
            <label>
              <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Angemeldet bleiben (30 Tage)
            </label>
          </p>
        )}
      </div>
    </main>
  );
}
