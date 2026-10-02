# WikingerBot — Command-Referenz

Alle Slash-Commands, was sie tun und welches Mindest-Berechtigungslevel
dafür nötig ist. Level-Hierarchie (siehe [README.md](README.md#berechtigungssystem)):
`Owner > Admin > Mod > Member`. Ein Discord-Server-Administrator
(`guild_permissions.administrator`) erfüllt automatisch jede Anforderung,
unabhängig von zugewiesenen Rollen.

Commands mit `📍` posten öffentlich sichtbare Antworten (z.B. Kick/Ban-
Bestätigungen), alle anderen antworten ephemer (nur der Ausführende sieht
die Antwort), teils mit automatischer Selbstlöschung nach ~20s.

Ausführlichere Erklärungen (nicht nur die Kurzbeschreibung hier):
[BANNER.md](BANNER.md) für den Status-Banner, [CONSOLE_FILTERS.md](CONSOLE_FILTERS.md)
für die Konsolen-Filter/Event-Muster inkl. Regex-Grundlagen.

---

## `/bot` — Bot-/Cog-Verwaltung (`admin`-Cog)

| Command | Beschreibung | Level |
|---|---|---|
| `/bot cog load name:` | Lädt ein Cog (Verzeichnisname unter `bot/cogs/`) | Owner |
| `/bot cog unload name:` | Entlädt ein Cog | Owner |
| `/bot cog reload name:` | Lädt ein Cog neu (Code-Änderungen übernehmen ohne Bot-Neustart) | Owner |
| `/bot cog list` | Listet geladene und verfügbare Cogs | Owner |
| `/bot web` | Schickt den Link zur Web-Oberfläche (nur für dich sichtbar). Die Adresse kommt aus `PUBLIC_URL` (AMP: *Web-Adresse*) | Mod |
| `/bot sync local: reset:` | Synct Slash-Commands (`local=True`: nur dieser Server, sofort sichtbar; `local=False`: global, bis zu 1h Verzögerung; `reset=True`: vorher alle Commands löschen) | Owner |
| `/bot sync_on_startup enabled:` | Steuert, ob beim Bot-Start automatisch global gesynct wird (Standard: an — nötig, damit eine frische Installation ohne manuellen Schritt Commands bekommt). Ohne `enabled` zeigt der aktuellen Stand an. In einer Dev-Umgebung mit zusätzlichem lokalem Sync sinnvoll abzuschalten, sonst entstehen doppelte Commands im Picker | Owner |

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
| `/server add name: amp_instance_id: display_name: host:` | Legt einen neuen Server-Eintrag an (`host` ist nur die Anzeige-Adresse für Spieler, Autocomplete schlägt bereits genutzte Adressen dieser Guild vor — bleibt aber freier Text). Erkennt die Steam-App-ID automatisch aus AMPs `DisplayImageSource`, falls vorhanden (siehe `/server steam_appid` für manuelle Korrektur) | Owner |
| `/server console_channel name: channel:` | Setzt/entfernt den Kanal für die Konsolen-Bridge | Owner |
| `/server chat_channel name: channel:` | Setzt/entfernt den Kanal für die Chat-Bridge (Discord → Spiel) | Owner |
| `/server event_channel name: channel:` | Setzt/entfernt den Kanal für erkannte Join/Leave-Events | Owner |
| `/server console_filter_mode name: mode:` | Rauschfilter-Modus: `off` / `blacklist` (Standard, blendet bekanntes Rauschen aus) / `whitelist` (nur eigene Muster zeigen) | Owner |
| `/server pattern_add name: kind: pattern:` | Fügt ein eigenes Regex-Muster hinzu (`kind`: `filter` oder `event`) | Owner |
| `/server pattern_remove name: pattern_id:` | Entfernt ein eigenes Muster | Owner |
| `/server pattern_toggle name: kind: key: enabled:` | Aktiviert/deaktiviert eines der eingebauten Muster für einen Server | Owner |
| `/server pattern_list name: kind:` | Zeigt eingebaute Muster (mit Status) + eigene Muster | Mod |
| `/server steam_appid name: appid:` | Überschreibt/löscht (`appid: 0`) die automatisch aus AMPs `DisplayImageSource` erkannte Steam-App-ID eines Servers — treibt den automatischen Artwork-Hintergrund im Banner | Owner |

**Konsolen-Bridge**: Neue AMP-Konsolenzeilen werden alle 2s abgefragt und je
nach `classify()`-Ergebnis (`bot/core/console_filters.py`) an den Konsolen-
oder Event-Kanal gesendet oder unterdrückt. Event-Erkennung hat immer
Vorrang vor Filter-Unterdrückung. Ausführliche Erklärung der Filter-Modi,
eingebauten Muster und Regex-Grundlagen: [CONSOLE_FILTERS.md](CONSOLE_FILTERS.md).

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
| `/modconfig log_channel channel:` | Kanal, in dem jeder Bann, Kick und Timeout gemeldet wird (Mod, Grund, bei Bann der `/unban`-Befehl). Ohne eigenen Kanal wird der AutoMod-Kanal benutzt | Owner |

**Rangregel**: Vor `/kick`, `/ban`, `/timeout`, `/warn` und jeder automatischen
Eskalation prüft der Bot Discords eigene Regel – das Ziel muss **unter** dem
Ausführenden **und** unter der Bot-Rolle stehen; den Server-Owner (und sich selbst)
kann niemand moderieren. Sonst könnte z.B. ein Mod über den Bot einen anderen Mod
bannen, was er direkt in Discord nicht dürfte. Lehnt Discord eine Aktion trotzdem
ab, gibt es eine Fehlermeldung statt eines hängenden Befehls (bei Kick/Bann erhält
der Betroffene dann eine Korrektur-DM).

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
| `/whitelist donator user: enabled:` | Setzt/entfernt den Donator-Status eines Nutzers (zeigt sich als Stern-Badge auf Bannern von Servern, bei denen dieser Nutzer freigeschaltet ist) | Owner |

Anfragen erscheinen im konfigurierten Kanal als Embed mit **Annehmen**/
**Ablehnen**-Buttons (neustart-sicher). Bei Freigabe: best-effort
AMP-Whitelist-Aufruf (`MinecraftModule.AddToWhitelist` — funktioniert nur
bei Minecraft-Instanzen, schlägt bei anderen Spielen erwartungsgemäß fehl
und wird nur im Ergebnis vermerkt), automatische Rollen-Vergabe falls
`Server.discord_role_id` gesetzt ist, DM an den Antragsteller. Es gibt kein
Auto-Approve — jede Anfrage braucht eine explizite Mod-Entscheidung.

---

## `/banner` — Status-Banner pro Server (`banner`-Cog)

Ausführliche Erklärung (Hintergrund-Priorität, Editor, Badges): [BANNER.md](BANNER.md).

| Command | Beschreibung | Level |
|---|---|---|
| `/banner enable name: channel: type:` | Aktiviert den Banner (`type`: `embed` oder `image`), postet ihn sofort | Owner |
| `/banner disable name:` | Deaktiviert den Banner, löscht die Nachricht | Owner |
| `/banner type name: type:` | Wechselt zwischen Embed- und Bild-Darstellung (Nachricht wird neu gepostet) | Owner |
| `/banner theme name: theme:` | Setzt ein eingebautes Verlaufs-Theme, löscht eigenes Hintergrundbild/Farben | Owner |
| `/banner background name: image:` | Lädt ein eigenes Hintergrundbild hoch (PNG/JPEG/WebP, max. 8 MB), löscht Theme/Farben | Owner |
| `/banner customize name:` | Interaktiver Editor (Start-/Endfarbe + Unschärfe ohne Hintergrundbild, sonst Schriftfarbe + Unschärfe) mit Live-Vorschau, Übernehmen-/Abbrechen-Buttons | Owner |
| `/banner refresh name:` | Aktualisiert den Banner sofort, ohne auf die 60s-Loop zu warten | Mod |

**Hintergrund-Priorität** (höchste zuerst): eigenes hochgeladenes Bild →
automatisch erkanntes Steam-Artwork (aus `Server.steam_app_id`, siehe
`/server steam_appid`) → eigene Verlaufsfarben (aus `/banner customize`) →
benanntes Theme → Standard-Theme. Ist ein Hintergrundbild aktiv, wirken
Start-/Endfarbe nicht (das Bild hat Vorrang) — der Editor bietet in dem
Fall stattdessen eine Schriftfarbe an.

Der Banner zeigt zusätzlich ein Whitelist-Badge (🔒 Anzahl freigeschalteter
Nutzer, ⭐ falls mind. einer davon Donator ist). Die Verbindungs-Adresse
steht einmalig als echter, kopierbarer Inline-Code-Text **über** der
Nachricht (nicht nochmal im Embed-Feld oder als Pixel im Bild — beides
wäre redundant und im Bild ohnehin nicht antippbar). Eine `tasks.loop(60s)`
aktualisiert alle aktiven Banner per `message.edit()` (kein Neu-Posten,
solange die Nachricht existiert); wiederholte Fehlschläge (z.B. ein
hängendes Rate-Limit) führen zu exponentiell steigenden Pausen statt
stur jede Minute erneut anzurennen.

---

## `/bannergroup` — mehrere Server in einem gemeinsamen Banner (`banner`-Cog)

| Command | Beschreibung | Level |
|---|---|---|
| `/bannergroup create name: channel: type: layout:` | Erstellt eine neue Banner-Gruppe (`layout`: `combined`/`separate`, Standard `combined`) | Owner |
| `/bannergroup layout group: layout:` | Wechselt nachträglich zwischen kombiniertem und einzelnem Layout | Owner |
| `/bannergroup add group: server:` | Fügt einen Server hinzu (max. 6 pro Gruppe), deaktiviert dessen Einzel-Banner falls aktiv | Owner |
| `/bannergroup remove group: server:` | Entfernt einen Server aus der Gruppe (individueller Banner bleibt deaktiviert, bis erneut per `/banner enable` aktiviert) | Owner |
| `/bannergroup theme group: theme:` | Wie `/banner theme` — nur im `combined`-Layout wirksam | Owner |
| `/bannergroup background group: image:` | Wie `/banner background` — nur im `combined`-Layout wirksam | Owner |
| `/bannergroup customize group:` | Wie `/banner customize` — nur im `combined`-Layout wirksam | Owner |
| `/bannergroup refresh group:` | Aktualisiert die Gruppe sofort | Mod |
| `/bannergroup disable group:` | Löst die Gruppe komplett auf (Mitglieder werden freigegeben, Nachricht gelöscht) | Owner |

Ein Server gehört zu maximal einer Gruppe. Zwei Layouts stehen zur Wahl:

- **`combined`** (Standard): ein gestapeltes Bild/ein Embed mit gemeinsamem
  Hintergrund/Theme/Farben/Unschärfe für die ganze Gruppe; jedes Mitglied
  bekommt darin ein eigenes kompaktes Panel (Status, Spieler, Verbinden,
  Whitelist-Badge).
- **`separate`** (wie GatekeeperV2): jedes Mitglied bekommt sein **eigenes**
  vollständiges Banner-Bild/-Embed (mit seinem eigenen Steam-Artwork/Theme/
  Farben, exakt wie ein Einzel-Banner) — alle zusammen als mehrere Anhänge/
  Embeds in einer gemeinsamen Nachricht. Die gruppenweiten `theme`/
  `background`/`customize`-Befehle wirken in diesem Layout nicht, da jedes
  Mitglied seine eigene Optik behält (dafür `/banner theme` usw. pro
  Mitgliedsserver nutzen).
