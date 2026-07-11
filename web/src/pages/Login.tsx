import { loginUrl } from "@/api/client";

export default function Login() {
  const guildId = import.meta.env.VITE_DISCORD_GUILD_ID;

  function handleLogin() {
    // Volle Seiten-Navigation (kein fetch!) - der Login-Endpunkt leitet zu
    // Discords eigener Domain weiter, das muss die SPA verlassen.
    window.location.href = loginUrl(guildId);
  }

  return (
    <main style={{ display: "flex", height: "100vh", alignItems: "center", justifyContent: "center" }}>
      <div style={{ textAlign: "center" }}>
        <h1>WikingerBot</h1>
        <button onClick={handleLogin}>Mit Discord anmelden</button>
      </div>
    </main>
  );
}
