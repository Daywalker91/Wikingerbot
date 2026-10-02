# WikingerBot — Setup

Diese Anleitung deckt die einmaligen, manuellen Schritte ab, die außerhalb von Code
passieren: Discord-Application anlegen, Bot einladen, Rollen-Hierarchie setzen.
Für die lokale Entwicklungsumgebung siehe [README.md](README.md).

---

## 1. Discord-Application & Bot-User anlegen

1. Auf https://discord.com/developers/applications eine neue Application erstellen.
2. Unter **Bot** einen Bot-User hinzufügen und den **Token** kopieren → in `.env` als
   `DISCORD_TOKEN` eintragen (siehe `.env.example`).
3. Unter **OAuth2 → General** die **Client ID** und das **Client Secret** kopieren →
   `.env` als `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET`. Diese Application-Daten
   werden doppelt gebraucht: einmal für den Bot-Invite (Schritt 3), einmal für den
   WebUI-Login (Discord-OAuth2, siehe `api/routers/auth.py`).
4. Ebenfalls unter **OAuth2 → General**, im Abschnitt "Redirects": die exakte
   `DISCORD_REDIRECT_URI` aus `.env` eintragen (Standard für lokale Entwicklung:
   `http://localhost:8000/auth/callback`) und speichern. Ohne diesen Eintrag
   lehnt Discord den Login mit "Ungültiges OAuth2 redirect_uri" ab — live
   verifiziert beim ersten Test des WebUI-Login-Flows.

### Privileged Gateway Intents

Unter **Bot → Privileged Gateway Intents** müssen folgende zwei Schalter aktiviert
werden — sie entsprechen genau dem, was `bot/core/bot.py` per Code anfordert
(`intents.members`, `intents.message_content`):

- **Server Members Intent**
- **Message Content Intent**

Ohne diese Häkchen verweigert Discord den Verbindungsaufbau, auch wenn der Code sie
anfordert.

---

## 2. Bot einladen

Invite-Link-Format:

```
https://discord.com/api/oauth2/authorize?client_id=<CLIENT_ID>&scope=bot+applications.commands&permissions=1374661241862
```

`<CLIENT_ID>` durch die eigene Client ID aus Schritt 1 ersetzen.

Die Berechtigungs-Zahl `1374661241862` deckt das ab, was Phase 1 + die geplanten
Phase-2-Cogs brauchen (mit `discord.Permissions(...).value` verifiziert):

| Berechtigung | Wofür |
|---|---|
| Kick Members, Ban Members, Moderate Members (Timeout) | `moderation`-Cog, `automod`-Cog (Timeout) |
| Manage Roles | `whitelist`-Cog (Rollen bei Freigabe), `roles`-Cog (Autorole, Selbstwahl-Rollen) |
| View Channel, Send Messages, Read Message History, Embed Links, Attach Files | Konsolen-/Chat-Bridge (`amp`-Cog), Bot-Antworten allgemein |
| Manage Messages | Aufräumen/Moderation, `automod`-Cog (löscht Verstöße) |
| Connect, Speak | `music`-Cog |

**Nicht im Link, bewusst:** *Kanäle verwalten* braucht nur der Mitgliederzähler des
`stats`-Cogs (`/stats zaehler`) – und nur für **diesen einen** Kanal. Darum dort in den
Kanal-Einstellungen → Berechtigungen der Bot-Rolle *Kanal verwalten* erlauben, statt dem
Bot das Recht serverweit zu geben.

Scope `applications.commands` ist zwingend nötig, damit die Slash-Commands
(`/bot cog ...` etc.) überhaupt in einem Server registriert werden können.

---

## 3. Rollen-Hierarchie setzen (wichtig!)

Nach dem Einladen legt Discord automatisch eine eigene Rolle für den Bot an. Diese
Rolle muss **manuell** in `Server-Einstellungen → Rollen` **über** allen Rollen
einsortiert werden, die der Bot verwalten soll:

- Rollen, die bei Whitelist-Freigabe automatisch vergeben werden sollen
  (`whitelist`-Cog, Phase 2)
- Rollen von Mitgliedern, die der Bot kicken/bannen/timeout soll

Das ist eine Discord-API-Einschränkung (ein Bot kann keine Rollen zuweisen/entfernen
oder Mitglieder moderieren, die eine höhere oder gleich hohe Rolle als der Bot selbst
haben) und lässt sich nicht per Code umgehen — GatekeeperV2 löst das genauso wenig
automatisch, es ist bei jedem Discord-Bot ein einmaliger manueller Schritt.

---

## 4. Berechtigungslevel im Bot konfigurieren

Nach dem Einladen müssen die eigenen Discord-Rollen (Owner/Admin/Mod) mit den
Berechtigungsleveln aus [WikingerBot.md](README.md#berechtigungssystem) verknüpft
werden. Das passiert über die `guild_roles`-Tabelle (`db/models/role.py`) — ein
Discord-Admin (`guild_permissions.administrator`) hat automatisch Owner-Level ohne
weitere Konfiguration; alle anderen Level müssen explizit über Rollen-IDs eingetragen
werden (aktuell nur direkt in der DB möglich, ein `/config role`-Command dafür folgt
in einer späteren Phase).
