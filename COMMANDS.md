# WikingerBot — Command-Referenz

Alle Slash-Commands, was sie tun und welches Mindest-Berechtigungslevel
dafür nötig ist. Level-Hierarchie (siehe [README.md](README.md#berechtigungssystem)):
`Owner > Admin > Mod > Member`. Ein Discord-Server-Administrator
(`guild_permissions.administrator`) erfüllt automatisch jede Anforderung,
unabhängig von zugewiesenen Rollen.

Commands mit `📍` posten öffentlich sichtbare Antworten (z.B. Kick/Ban-
Bestätigungen), alle anderen antworten ephemer (nur der Ausführende sieht
die Antwort), teils mit automatischer Selbstlöschung nach ~20s.

---

## `/bot` — Bot-/Cog-Verwaltung (`admin`-Cog)

| Command | Beschreibung | Level |
|---|---|---|
| `/bot cog load name:` | Lädt ein Cog (Verzeichnisname unter `bot/cogs/`) | Owner |
| `/bot cog unload name:` | Entlädt ein Cog | Owner |
| `/bot cog reload name:` | Lädt ein Cog neu (Code-Änderungen übernehmen ohne Bot-Neustart) | Owner |
| `/bot cog list` | Listet geladene und verfügbare Cogs | Owner |
| `/bot sync local: reset:` | Synct Slash-Commands (`local=True`: nur dieser Server, sofort sichtbar; `local=False`: global, bis zu 1h Verzögerung; `reset=True`: vorher alle Commands löschen) | Owner |

---

## `/server` — AMP-Serververwaltung (`amp`-Cog)

| Command | Beschreibung | Level |
|---|---|---|
| `/server list` | Listet alle konfigurierten Server mit Live-Status | Member |
| `/server status name:` | Detail-Status (Zustand, Uptime, Verbindungsadresse) eines Servers | Member |
| `/server start name:` | 📍 Startet einen Server über den AMP-Controller | Mod |
| `/server stop name:` | 📍 Stoppt einen Server | Mod |
| `/server console name: command:` | Sendet einen rohen Konsolenbefehl an die Instanz | Mod |
| `/server discover` | Listet AMP-Instanzen, die am Controller bekannt, aber noch nicht angelegt sind | Owner |
| `/server add name: amp_instance_id: display_name: host:` | Legt einen neuen Server-Eintrag an (`host` ist nur die Anzeige-Adresse für Spieler) | Owner |
| `/server console_channel name: channel:` | Setzt/entfernt den Kanal für die Konsolen-Bridge | Owner |
| `/server chat_channel name: channel:` | Setzt/entfernt den Kanal für die Chat-Bridge (Discord → Spiel) | Owner |
| `/server event_channel name: channel:` | Setzt/entfernt den Kanal für erkannte Join/Leave-Events | Owner |
| `/server console_filter_mode name: mode:` | Rauschfilter-Modus: `off` / `blacklist` (Standard, blendet bekanntes Rauschen aus) / `whitelist` (nur eigene Muster zeigen) | Owner |
| `/server pattern_add name: kind: pattern:` | Fügt ein eigenes Regex-Muster hinzu (`kind`: `filter` oder `event`) | Owner |
| `/server pattern_remove name: pattern_id:` | Entfernt ein eigenes Muster | Owner |
| `/server pattern_toggle name: kind: key: enabled:` | Aktiviert/deaktiviert eines der eingebauten Muster für einen Server | Owner |
| `/server pattern_list name: kind:` | Zeigt eingebaute Muster (mit Status) + eigene Muster | Mod |

**Konsolen-Bridge**: Neue AMP-Konsolenzeilen werden alle 2s abgefragt und je
nach `classify()`-Ergebnis (`bot/core/console_filters.py`) an den Konsolen-
oder Event-Kanal gesendet oder unterdrückt. Event-Erkennung hat immer
Vorrang vor Filter-Unterdrückung.

**Chat-Bridge**: Nachrichten im konfigurierten `chat_channel` werden als
`say <Name>: <Text>`-Konsolenbefehl an die Instanz weitergeleitet — wirkt
nur, wenn das jeweilige Spiel einen solchen Konsolenbefehl kennt (z.B.
Minecraft; vanilla Valheim z.B. nicht).

---

## Moderation (`moderation`-Cog, top-level Commands)

| Command | Beschreibung | Level |
|---|---|---|
| `/kick user: reason:` | 📍 Kickt ein Mitglied, DM mit Grund (best-effort), ModLog-Eintrag | Mod |
| `/ban user: reason: delete_message_days:` | 📍 Bannt ein Mitglied (optional Nachrichten der letzten 0-7 Tage löschen) | Mod |
| `/unban user_id: reason:` | 📍 Hebt einen Bann per Discord-User-ID auf | Mod |
| `/timeout user: duration_minutes: reason:` | 📍 Timeoutet ein Mitglied (max. 40320 Min. = 28 Tage) | Mod |
| `/warn user: reason: points:` | 📍 Verwarnt ein Mitglied (Default 1 Punkt), siehe Warn-Eskalation unten | Mod |
| `/warnings user:` | Zeigt aktive (nicht abgelaufene) Verwarnungen eines Mitglieds | Mod |
| `/modlog user:` | Zeigt die komplette Moderationshistorie eines Mitglieds | Mod |
| `/modconfig threshold value:` | Setzt die Warn-Punkte-Schwelle für automatische Eskalation (Default 3) | Owner |
| `/modconfig action action:` | Setzt die Eskalations-Aktion: `timeout` / `ban` / `kick` (Default `timeout`) | Owner |
| `/modconfig timeout minutes:` | Setzt die Timeout-Dauer für Eskalationen in Minuten (Default 60) | Owner |

**Warn-Eskalation**: Erreicht ein Mitglied die konfigurierte Punkteschwelle,
werden `timeout`/`ban` **sofort automatisch ausgeführt** und danach per
"Bestätigen"/"Aufheben"-Buttons nachträglich geprüft (neustart-sicher).
`kick` wird **nie automatisch** ausgeführt — nur als Vorschlag mit
"Ausführen"-Button gepostet, ein Mod muss aktiv bestätigen.

---

## `/whitelist` — Whitelist-Verwaltung (`whitelist`-Cog)

| Command | Beschreibung | Level |
|---|---|---|
| `/whitelist channel channel:` | Setzt den Kanal, in dem Anfragen zur Freigabe erscheinen (Mods/Admins) | Owner |
| `/whitelist request server: ign:` | Beantragt Whitelist-Zugang; `ign` weglassen, um den zuletzt genutzten In-Game-Namen wiederzuverwenden | Member |
| `/whitelist list status:` | Listet Anfragen nach Status (Default: `pending`) | Mod |
| `/whitelist approve request_id:` | Genehmigt eine Anfrage (Fallback zum Accept-Button) | Mod |
| `/whitelist deny request_id: reason:` | Lehnt eine Anfrage ab (Fallback zum Deny-Button) | Mod |

Anfragen erscheinen im konfigurierten Kanal als Embed mit **Annehmen**/
**Ablehnen**-Buttons (neustart-sicher). Bei Freigabe: best-effort
AMP-Whitelist-Aufruf (`MinecraftModule.AddToWhitelist` — funktioniert nur
bei Minecraft-Instanzen, schlägt bei anderen Spielen erwartungsgemäß fehl
und wird nur im Ergebnis vermerkt), automatische Rollen-Vergabe falls
`Server.discord_role_id` gesetzt ist, DM an den Antragsteller. Es gibt kein
Auto-Approve — jede Anfrage braucht eine explizite Mod-Entscheidung.
