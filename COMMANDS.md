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
| `/bot web` | Schickt den Link zur Web-Oberfläche (nur für dich sichtbar). Adresse aus `PUBLIC_URL` (AMP: *Web-Adresse*), sonst der Link der Instanz laut AMP | Mod |
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

---

## `/welcome` — Begrüßung neuer Mitglieder (`welcome`-Cog)

Texte kennen die Platzhalter `{user}` (Erwähnung), `{name}` (Anzeigename),
`{server}` und `{count}` (Mitgliederzahl); `\n` im Text wird zum Zeilenumbruch.
Gepingt wird nur das neue Mitglied – `@everyone` oder Rollen im Text lösen
keinen Ping aus. Bots werden weder begrüßt noch verabschiedet.

| Command | Beschreibung | Level |
|---|---|---|
| `/welcome kanal kanal:` | Kanal für die Begrüßung; ohne Angabe ist die Begrüßung aus | Admin |
| `/welcome text text:` | Text der Begrüßung (zeigt gleich eine Vorschau) | Admin |
| `/welcome dm text:` | Zusätzliche DM an neue Mitglieder, z.B. Regeln und Link zur Seite; `aus` schaltet ab | Admin |
| `/welcome abschied aktiv: text: kanal:` | Meldung, wenn jemand geht; ohne eigenen Kanal im Begrüßungskanal | Admin |
| `/welcome test` | Zeigt Begrüßung, DM und Abschied mit dir als Beispiel | Admin |

---

## `/rollen` — Autorole und Selbstwahl-Rollen (`roles`-Cog)

**Autorole:** Neue Mitglieder bekommen die eingetragenen Rollen automatisch. Ist
Discords Regel-Screening aktiv, erst nachdem sie die Regeln akzeptiert haben.

**Selbstwahl-Rollen:** Eine Bot-Nachricht („Panel“) mit Knöpfen; jeder Knopf
schaltet eine Rolle an oder aus (z.B. Spiele-Rollen zum gezielten Pingen). Die
Knöpfe funktionieren auch nach einem Neustart weiter. Ablauf:
`/rollen panel erstellen` → Link der Nachricht kopieren → pro Rolle einmal
`/rollen panel knopf`.

Aus Sicherheitsgründen nicht vergebbar: `@everyone`, von Integrationen verwaltete
Rollen, Rollen über der Bot-Rolle, Rollen mit Verwaltungsrechten (Administrator,
Rollen/Kanäle/Server verwalten, Bannen, Kicken, Timeout, …) und – bei den
Knöpfen – die Berechtigungsrollen des Bots (Mod/Admin/…). Braucht das Bot-Recht
**Rollen verwalten**.

| Command | Beschreibung | Level |
|---|---|---|
| `/rollen auto hinzufuegen rolle:` | Rolle wird neuen Mitgliedern automatisch gegeben | Admin |
| `/rollen auto entfernen rolle:` | Rolle nicht mehr automatisch vergeben | Admin |
| `/rollen auto liste` | Zeigt die Autoroles, mit Warnung bei nicht vergebbaren | Admin |
| `/rollen panel erstellen kanal: titel: text:` | Postet die Panel-Nachricht | Admin |
| `/rollen panel knopf nachricht: rolle: beschriftung: emoji:` | Knopf hinzufügen (max. 25 pro Panel); `nachricht` = Link oder ID | Admin |
| `/rollen panel entfernen nachricht: rolle:` | Knopf entfernen | Admin |

---

## `/musik` — Radio, eigene Dateien und Podcasts (`music`-Cog)

Ersetzt Sinusbot. Bewusst **ohne** YouTube, Spotify und Aufnahme. Der Bot kommt
in deinen Voice-Kanal; verlässt ihn von selbst, wenn niemand mehr zuhört oder 5
Minuten nichts lief. Steuern (Pause, Skip, Stopp, Lautstärke) darf, wer im selben
Voice-Kanal ist – Mods immer. Eigene Dateien gehören nach `data/music` (in AMP:
Dateimanager → `Wikingerbot-main/data/music`), Unterordner sind Playlisten;
erlaubt sind mp3, ogg, opus, flac, wav, m4a, aac.

| Command | Beschreibung | Level |
|---|---|---|
| `/musik radio sender:` | Spielt einen eingetragenen Radiosender | Member |
| `/musik datei datei:` | Spielt eine eigene Datei | Member |
| `/musik ordner ordner: zufall:` | Reiht alle Dateien eines Ordners ein | Member |
| `/musik podcast feed: folge:` | Spielt eine Podcast-Folge, ohne Auswahl die neueste | Member |
| `/musik url url:` | Stream, .m3u/.pls oder Audiodatei von einer Adresse (keine internen Adressen) | Mod |
| `/musik pause` · `weiter` · `skip` · `stopp` | Wiedergabe steuern; `stopp` leert die Warteschlange und verlässt den Kanal | im Kanal / Mod |
| `/musik lautstaerke wert:` | 0–100, Standard 50 | im Kanal / Mod |
| `/musik mischen` | Mischt die Warteschlange | im Kanal / Mod |
| `/musik warteschlange` | Was läuft und was kommt | Member |
| `/musikconfig sender_hinzufuegen name: url:` | Radiosender eintragen (Stream oder .m3u/.pls) | Admin |
| `/musikconfig sender_entfernen name:` · `sender_liste` | Sender entfernen / anzeigen | Admin / Member |
| `/musikconfig podcast_abonnieren name: url:` | Podcast per RSS-Feed eintragen | Admin |
| `/musikconfig podcast_entfernen name:` | Podcast entfernen | Admin |
| `/musikconfig podcast_ankuendigen name: kanal:` | Neue Folgen im Kanal ankündigen (Prüfung alle 30 min); ohne Kanal aus | Admin |
| `/musikconfig dateien` | Zeigt Ordner und Anzahl der eigenen Dateien | Admin |

---

## `/stats` — Server-Statistiken (`stats`-Cog)

Zählt Beitritte, Austritte, Nachrichten und Voice-Zeit (ohne AFK-Kanal), je Tag in
der Zeitzone Europe/Vienna. Gezählt wird **nur die Anzahl, nie der Inhalt**; Werte
pro Mitglied werden nach 90 Tagen gelöscht (`/stats aufbewahrung`). Bots zählen
nicht mit. Gespeichert wird einmal pro Minute.

| Command | Beschreibung | Level |
|---|---|---|
| `/stats server tage:` | 📍 Übersicht: Mitglieder, Beitritte/Austritte, Nachrichten, Voice-Zeit, aktivster Tag, Top 5 | Member |
| `/stats mitglied mitglied: tage:` | Nachrichten, Platz und Voice-Zeit eines Mitglieds (ohne Angabe: deine) | Member |
| `/stats zaehler kanal: format:` | Kanalname zeigt die Mitgliederzahl, z.B. `👥 Mitglieder: {count}`; alle 10 min aktualisiert, ohne Kanal aus. Braucht das Bot-Recht **Kanäle verwalten** für diesen Kanal | Admin |
| `/stats aufbewahrung tage:` | Wie lange Werte pro Mitglied gespeichert bleiben (7–730 Tage) | Admin |

---

## `/automod` — eigene AutoMod-Regeln (`automod`-Cog)

**Ergänzung** zu Discords eingebautem AutoMod (Stichwörter, Erwähnungs-Spam,
verdächtige Inhalte macht Discord selbst; deren Treffer verarbeitet der
`moderation`-Cog). Hier nur, was Discord nicht kann. Standardmäßig **aus**
(`/automod aktiv an:True`). Mods, Admins und Server-Administratoren sind immer
ausgenommen. Bei einem Verstoß: Nachricht löschen, kurzer Hinweis im Kanal,
optional Warn-Punkte (über das Verwarnsystem von `moderation`) und Timeout,
Meldung im Alarmkanal. Während einer Flut wird nur einmal pro 30 s bestraft.

| Command | Beschreibung | Level |
|---|---|---|
| `/automod status` | Alle Regeln und Einstellungen | Mod |
| `/automod aktiv an:` | Bot-AutoMod an/aus | Admin |
| `/automod flut an: nachrichten: sekunden:` | Mehr als X Nachrichten in Y Sekunden (Standard 6 in 8 s) | Admin |
| `/automod wiederholung an: anzahl: sekunden:` | Gleiche Nachricht X-mal in Y Sekunden (Standard 3 in 60 s) | Admin |
| `/automod grossbuchstaben an: prozent: mindestlaenge:` | Zu viel Großschrift (Standard ab 70 % bei mind. 12 Buchstaben) | Admin |
| `/automod emojis an: maximal:` | Mehr als X Emojis (Standard 10) | Admin |
| `/automod links modus:` | `aus`, `nur_erlaubte` (Liste unten) oder `alle_sperren`; Discord-Einladungen zählen als `discord.gg` | Admin |
| `/automod link_erlauben domain:` · `link_entfernen domain:` | Erlaubte Domains (gilt mit Subdomains) | Admin |
| `/automod neue_konten tage:` | Hinweis im Alarmkanal, wenn ein jüngeres Konto beitritt (0 = aus) | Admin |
| `/automod aktion loeschen: punkte: timeout_minuten:` | Folgen eines Verstoßes (Standard: nur löschen) | Admin |
| `/automod alarmkanal kanal:` | Kanal für Meldungen – derselbe wie für Discords AutoMod | Admin |
| `/automod ausnahme kanal: rolle:` | Kanal/Rolle ausnehmen; nochmal aufrufen hebt es auf | Admin |

---

## Community-Seite (`community`-Cog)

Nur aktiv, wenn die Datenbank der Seite angebunden ist (Bot-Oberfläche → *Community*, siehe [AMP.md](AMP.md)). Grundlage für
die weiteren Community-Cogs: holt alle 5 Sekunden die Aufträge der Seite ab.

| Command | Beschreibung | Level |
|---|---|---|
| `/verknuepfen code:` | Verknüpft dein Discord-Konto mit deinem Konto auf der Seite. Den Code (8 Zeichen, 15 min gültig) gibt es auf der Seite unter *Einstellungen → Discord* | Member |
| `/verknuepfung_loesen` | Löst die Verknüpfung; deine Discord-Rollen bleiben | Member |
| `/profil mitglied:` | Link zum Profil auf der Seite und Rang (ohne Angabe: deins) | Member |
| `/community status` | Erreichbarkeit der Seiten-Datenbank, verknüpfte Mitglieder, offene/fehlgeschlagene Aufträge | Admin |
