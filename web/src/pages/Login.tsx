import { useEffect, useState } from "react";

import { apiFetch, loginUrl } from "@/api/client";

interface Guild {
  id: string;
  name: string;
}

export default function Login() {
  const [guilds, setGuilds] = useState<Guild[] | null>(null);

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
    window.location.href = loginUrl(guildId);
  }

  return (
    <main style={{ display: "flex", height: "100vh", alignItems: "center", justifyContent: "center" }}>
      <div style={{ textAlign: "center" }}>
        <h1>WikingerBot</h1>
        {guilds === null && <p>Lade …</p>}
        {guilds?.length === 0 && <p>Der Bot ist noch auf keinem Discord-Server.</p>}
        {guilds?.length === 1 && <button onClick={() => handleLogin(guilds[0].id)}>Mit Discord anmelden</button>}
        {guilds && guilds.length > 1 &&
          guilds.map((guild) => (
            <p key={guild.id}>
              <button onClick={() => handleLogin(guild.id)}>Bei „{guild.name}“ anmelden</button>
            </p>
          ))}
      </div>
    </main>
  );
}
