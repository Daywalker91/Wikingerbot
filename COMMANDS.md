# WikingerBot — Command-Referenz

Alle Slash-Commands, was sie tun und welches Mindest-Berechtigungslevel
dafür nötig ist. Level-Hierarchie (siehe [README.md](README.md#berechtigungssystem)):
`Owner > Admin > Mod > Member`. Ein Discord-Server-Administrator
(`guild_permissions.administrator`) erfüllt automatisch jede Anforderung,
unabhängig von zugewiesenen Rollen.

**Mod\***: Diese Befehle dürfen außer Mods auch Discord-Rollen, denen im Tab
*Einstellungen → Zusatz-Berechtigungen* die passende Fähigkeit gegeben wurde
(`server.control`, `whitelist.review`, `banner.refresh`) – z.B. Gameserver-Betreuer,
die keine Mods sind. Dasselbe gilt für die entsprechenden Knöpfe in der Oberfläche.

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
| `/server start name:` | 📍 Startet einen Server über den AMP-Controller | Mod\* |
| `/server stop name:` | 📍 Stoppt einen Server | Mod\* |
| `/server console name: command:` | Sendet einen rohen Konsolenbefehl an die Instanz | Mod\* |
| `/server discover` | Listet AMP-Instanzen, die am Controller bekannt, aber noch nicht angelegt sind. Instanzen von Discord-Servern, auf denen der Bot nicht mehr ist, gelten als frei; `/server add` übernimmt sie samt eigener Muster (Kanäle, Banner und Whitelist-Rolle neu setzen) | Owner |
| `/server add name: amp_instance_id: display_name: [host:]` | Legt einen neuen Server-Eintrag an. `host` ist nur die Anzeige-Adresse für Spieler und optional: leer = Standard-Spieladresse (Tab *Server*, sonst der Host aus `PUBLIC_URL`); ohne Port hängt der Bot den Spiel-Port an, den AMP für die Instanz meldet – bei jeder Anzeige frisch, Port-Änderungen in AMP kommen also mit. Ein eigener Port im Eintrag hat Vorrang. Erkennt die Steam-App-ID automatisch aus AMPs `DisplayImageSource`, falls vorhanden (siehe `/server steam_appid` für manuelle Korrektur) | Owner |
| `/server remove name:` | Entfernt einen Server-Eintrag nach Rückfrage – mit eigenen Mustern, Filter-Ausnahmen und Whitelist-Anfragen; der Banner wird gelöscht. Die AMP-Instanz bleibt bestehen. Auch im Tab *Server* (Knopf *Entfernen*) | Owner |
| `/server whitelist name: aktiv: rolle:` | Whitelist an/aus und Discord-Rolle des Servers (siehe Whitelist) | Owner |
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
| `/strafrolle geben mitglied: grund:` | Einschränken statt kicken: nimmt die Autorole, gibt die Strafrolle (Tab Moderation), DM mit Grund, Modlog-Eintrag | Mod |
| `/strafrolle aufheben mitglied: grund:` | Nimmt die Strafrolle, gibt die Autorole zurück | Mod |
| `/reset_escalation user:` | Setzt die Eskalationsstufe eines Mitglieds zurück (die nächste automatische Eskalation beginnt wieder unten in der Leiter) | Mod |
| `/modconfig threshold value:` | Setzt die Warn-Punkte-Schwelle für automatische Eskalation (Default 3) | Owner |
| `/modconfig ladder actions:` | Eskalations-Leiter, z.B. `timeout,strafrolle,kick,ban` | Owner |
| `/modconfig timeout minutes:` | Setzt die Timeout-Dauer für Eskalationen in Minuten (Default 60) | Owner |
| `/modconfig decay_days days:` | Nach wie vielen Tagen Warn-Punkte automatisch verfallen | Owner |
| `/modconfig log_channel channel:` | Kanal, in dem jeder Bann, Kick und Timeout gemeldet wird (Mod, Grund, bei Bann der `/unban`-Befehl). Auch im Moderations-Tab einstellbar. Wer bisher keinen eigenen hatte, behält einmalig den bisherigen AutoMod-Kanal | Owner |

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
"Ausführen"-Button gepostet, ein Mod muss aktiv bestätigen. `strafrolle` gibt
automatisch die Strafrolle.

**Strafrolle**: Eine Discord-Rolle, die weniger darf (die Rechte stellt man in
Discord ein, z.B. nur lesen). Der Bot merkt sich jeden, der sie hat – egal ob per
Befehl, Eskalation, Rang-Sync oder von Hand vergeben. Wer damit den Server
verlässt und wiederkommt, bekommt beim Beitritt wieder die Strafrolle statt der
Autorole. Ist die Community-Seite angebunden und das Mitglied verknüpft, bekommt
es beim (Wieder-)Beitritt außerdem den Rang der Seite.

---

## `/whitelist` — Whitelist-Verwaltung (`whitelist`-Cog)

| Command | Beschreibung | Level |
|---|---|---|
| `/whitelist channel channel:` | Setzt den Kanal, in dem Anfragen zur Freigabe erscheinen (Mods/Admins) | Owner |
| `/whitelist request server: ign:` | Beantragt Whitelist-Zugang (nur Server mit eingeschalteter Whitelist); `ign` weglassen, um den zuletzt genutzten In-Game-Namen wiederzuverwenden | Member |
| `/whitelist list status:` | Listet Anfragen nach Status (Default: `pending`) | Mod\* |
| `/whitelist approve request_id:` | Genehmigt eine Anfrage (Fallback zum Accept-Button) | Mod\* |
| `/whitelist deny request_id: reason:` | Lehnt eine Anfrage ab (Fallback zum Deny-Button) | Mod\* |
| `/whitelist entziehen mitglied: server: rolle: grund:` | Entzieht eine Freigabe: mit `server` AMP-Eintrag und Discord-Rolle weg (die Rolle bleibt, solange eine Freigabe für einen anderen Server mit derselben Rolle besteht); mit `rolle` eine Gruppen-Rolle (Panel mit Bestätigung, auch von Hand vergebene). DM mit Grund. Auch im Tab *Whitelist* (Knopf *Entziehen*) | Mod\* |
| `/whitelist donator user: enabled:` | Setzt/entfernt den Donator-Status eines Nutzers (zeigt sich als Stern-Badge auf Bannern von Servern, bei denen dieser Nutzer freigeschaltet ist) | Owner |

Anfragen erscheinen im konfigurierten Kanal als Embed mit **Annehmen**/
**Ablehnen**-Buttons (neustart-sicher). Bei Freigabe: best-effort
AMP-Whitelist-Aufruf (`MinecraftModule.AddToWhitelist` — funktioniert nur
bei Minecraft-Instanzen, schlägt bei anderen Spielen erwartungsgemäß fehl
und wird nur im Ergebnis vermerkt), automatische Rollen-Vergabe falls
beim Server eine Rolle eingestellt ist, DM an den Antragsteller. Es gibt kein
Auto-Approve — jede Anfrage braucht eine explizite Mod-Entscheidung. Dasselbe
passiert beim Genehmigen in der Weboberfläche.

**Whitelist pro Server** (`/server whitelist name: aktiv: rolle:` oder Tab *Server*):
Jeder Server hat eine Discord-Rolle (z.B. für seinen Chat) und eine Whitelist an/aus.
- **An:** Die Rolle gibt es nur per Freigabe. `/whitelist request` bietet nur diese
  Server an; Selbstwahl-Knöpfe und Autorole verweigern die Rolle. **Im Discord-Onboarding
  darf die Rolle dann nicht als Antwort vergeben werden** – das kann der Bot nicht sperren.
- **Aus:** Die Rolle ist frei wählbar (Knöpfe, Onboarding), eine Whitelist-Anfrage gibt
  es nicht.
Mehrere Server können dieselbe Rolle haben (z.B. ein ARK-Cluster).

---

## `/banner` — Status-Banner pro Server (`banner`-Cog)

Ausführliche Erklärung (Hintergrund-Priorität, Editor, Badges): [BANNER.md](BANNER.md).
Alles hier geht auch im Tab *Banner* der Weboberfläche, mit Live-Vorschau.

| Command | Beschreibung | Level |
|---|---|---|
| `/banner enable name: channel: type:` | Aktiviert den Banner (`type`: `embed` oder `image`), postet ihn sofort | Owner |
| `/banner disable name:` | Deaktiviert den Banner, löscht die Nachricht | Owner |
| `/banner type name: type:` | Wechselt zwischen Embed- und Bild-Darstellung (Nachricht wird neu gepostet) | Owner |
| `/banner theme name: theme:` | Setzt ein eingebautes Verlaufs-Theme, löscht eigenes Hintergrundbild/Farben | Owner |
| `/banner background name: image:` | Lädt ein eigenes Hintergrundbild hoch (PNG/JPEG/WebP, max. 8 MB), löscht Theme/Farben | Owner |
| `/banner customize name:` | Interaktiver Editor (Start-/Endfarbe + Unschärfe ohne Hintergrundbild, sonst Schriftfarbe + Unschärfe) mit Live-Vorschau, Übernehmen-/Abbrechen-Buttons | Owner |
| `/banner refresh name:` | Aktualisiert den Banner sofort, ohne auf die 60s-Loop zu warten | Mod\* |

**Hintergrund-Priorität** (höchste zuerst): eigenes hochgeladenes Bild →
automatisch erkanntes Steam-Artwork (aus `Server.steam_app_id`, siehe
`/server steam_appid`) → eigene Verlaufsfarben (aus `/banner customize`) →
benanntes Theme → Standard-Theme. Ist ein Hintergrundbild aktiv, wirken
Start-/Endfarbe nicht (das Bild hat Vorrang) — der Editor bietet in dem
Fall stattdessen eine Schriftfarbe an.

Der Banner zeigt zusätzlich ein Whitelist-Badge (🔒 Anzahl freigeschalteter
Nutzer, ⭐ falls mind. einer davon Donator ist). Jeder Banner ist eine Karte
(Embed): oben die Verbindungs-Adresse als kopierbarer Inline-Code-Text, darunter
Status bzw. das Bild, Rand in Statusfarbe (nicht als Pixel im Bild — dort wäre
sie nicht antippbar). Eine `tasks.loop(60s)`
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
| `/bannergroup refresh group:` | Aktualisiert die Gruppe sofort | Mod\* |
| `/bannergroup disable group:` | Löst die Gruppe komplett auf (Mitglieder werden freigegeben, Nachricht gelöscht) | Owner |

Ein Server gehört zu maximal einer Gruppe. Zwei Layouts stehen zur Wahl:

- **`combined`** (Standard): ein gestapeltes Bild/ein Embed mit gemeinsamem
  Hintergrund/Theme/Farben/Unschärfe für die ganze Gruppe; jedes Mitglied
  bekommt darin ein eigenes kompaktes Panel (Status, Spieler, Verbinden,
  Whitelist-Badge).
- **`separate`**: jedes Mitglied bekommt sein **eigenes**
  vollständiges Banner-Bild/-Embed (mit seinem eigenen Steam-Artwork/Theme/
  Farben, exakt wie ein Einzel-Banner) — alle zusammen als Karten
  untereinander in einer gemeinsamen Nachricht, jede mit ihrer Adresse. Die gruppenweiten `theme`/
  `background`/`customize`-Befehle wirken in diesem Layout nicht, da jedes
  Mitglied seine eigene Optik behält (dafür `/banner theme` usw. pro
  Mitgliedsserver nutzen).

---

## `/welcome` — Begrüßung neuer Mitglieder (`welcome`-Cog)

Texte kennen die Platzhalter `{user}` (Erwähnung), `{name}` (Anzeigename),
`{server}` und `{count}` (Mitgliederzahl); `\n` im Text wird zum Zeilenumbruch.
Gepingt wird nur das neue Mitglied – `@everyone` oder Rollen im Text lösen
keinen Ping aus. Bots werden weder begrüßt noch verabschiedet. Nutzt der Server
Discords Mitgliedschaftsprüfung (Regeln/Onboarding), kommen Begrüßung und DM erst,
wenn das Mitglied die Regeln akzeptiert hat.

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

**Mit Bestätigung** (Haken pro Knopf bzw. `bestaetigung:`): Ein Klick gibt die Rolle
nicht sofort, sondern stellt eine **Gruppen-Anfrage** – wie eine Whitelist, nur ohne
Gameserver (z.B. für eine Spielgruppe). Sie erscheint im Whitelist-Kanal mit
*Annehmen/Ablehnen*; entscheiden darf, wer Whitelist-Anfragen bearbeiten darf
(Fähigkeit `whitelist.review`), nie bei der eigenen Anfrage. Ergebnis per DM, wieder
wegnehmen mit `/whitelist entziehen mitglied: rolle:` oder im Tab *Whitelist*
(Abschnitt *Gruppen-Rollen*). Abwählen geht immer sofort. Grenzen: je Rolle eine offene
Anfrage, eine pro Tag, höchstens vier pro Woche, nach Ablehnung sieben Tage Pause.

**Zusatzrollen der Community-Seite** (im Rang-Sync mit einer Discord-Rolle verknüpft,
z.B. Schmied): Ein Klick auf deren Knopf wird immer zur **Rollenanfrage auf der Seite**
(mit Ticket, Regeln der Rollenanfragen, z.B. AMP-Konto nach Zustimmung) – verknüpfte
Mitglieder; abgeben geht über die Seite bzw. das Team.

Alles hier geht auch im Tab *Rollen* der Weboberfläche: Autoroles wählen, Panels
anlegen, Titel/Text ändern, Knöpfe hinzufügen, entfernen und umsortieren. Panels,
die vor dem Tab per Befehl erstellt wurden, lassen sich dort per Link übernehmen.

| Command | Beschreibung | Level |
|---|---|---|
| `/rollen auto hinzufuegen rolle:` | Rolle wird neuen Mitgliedern automatisch gegeben | Admin |
| `/rollen auto entfernen rolle:` | Rolle nicht mehr automatisch vergeben | Admin |
| `/rollen auto liste` | Zeigt die Autoroles, mit Warnung bei nicht vergebbaren | Admin |
| `/rollen panel erstellen kanal: titel: text:` | Postet die Panel-Nachricht | Admin |
| `/rollen panel knopf nachricht: rolle: beschriftung: emoji: bestaetigung:` | Knopf hinzufügen (max. 25 pro Panel); `nachricht` = Link oder ID; `bestaetigung: True` = Klick stellt nur eine Anfrage (siehe unten) | Admin |
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
| `/musik playlist url: zufall:` | Alle Titel einer .m3u/.pls-Playlist einreihen (bis 200, z.B. von GitHub – Raw-Adresse) | Mod |
| `/musik pause` · `weiter` · `skip` · `stopp` | Wiedergabe steuern; `stopp` leert die Warteschlange und verlässt den Kanal | im Kanal / Mod |
| `/musik lautstaerke wert:` | 0–100, Standard 50 | im Kanal / Mod |
| `/musik mischen` | Mischt die Warteschlange | im Kanal / Mod |
| `/musik warteschlange` | Was läuft und was kommt | Member |
| `/musikconfig sender_hinzufuegen name: url:` | Radiosender eintragen (Stream oder .m3u/.pls); gleiche Adresse oder gleicher Name wird abgelehnt | Admin |
| `/musikconfig sender_import url:` | Alle Sender einer .m3u/.pls-Liste eintragen (Namen aus der Liste, bis 200; vorhandene Adressen werden übersprungen). Auch im Tab *Musik* | Admin |
| `/musikconfig sender_entfernen name:` · `sender_liste` | Sender entfernen / anzeigen | Admin / Member |
| `/musikconfig podcast_abonnieren name: url:` | Podcast per RSS-Feed eintragen | Admin |
| `/musikconfig podcast_entfernen name:` | Podcast entfernen | Admin |
| `/musikconfig podcast_ankuendigen name: kanal:` | Neue Folgen im Kanal ankündigen (Prüfung alle 30 min); ohne Kanal aus | Admin |
| `/musikconfig dateien` | Zeigt Ordner und Anzahl der eigenen Dateien | Admin |

---

## `/stats` — Server-Statistiken (`stats`-Cog)

Zählt Beitritte, Austritte, Nachrichten und Voice-Zeit (ohne AFK-Kanal), je Tag in
der Zeitzone aus `TIMEZONE` (Standard Europe/Berlin). Gezählt wird **nur die Anzahl, nie der Inhalt**; Werte
pro Mitglied werden nach 90 Tagen gelöscht (`/stats aufbewahrung`). Bots zählen
nicht mit. Gespeichert wird einmal pro Minute.

| Command | Beschreibung | Level |
|---|---|---|
| `/stats server tage:` | 📍 Übersicht: Mitglieder, Beitritte/Austritte, Nachrichten, Voice-Zeit, aktivster Tag, Top 5 | Member |
| `/stats mitglied mitglied: tage:` | Nachrichten, Platz und Voice-Zeit eines Mitglieds (ohne Angabe: deine) | Member |
| `/stats zaehler kanal: format:` | Kanalname zeigt die Mitgliederzahl, z.B. `👥 Mitglieder: {count}`; alle 10 min aktualisiert, ohne Kanal aus. Braucht das Bot-Recht **Kanäle verwalten** für diesen Kanal | Admin |
| `/stats aufbewahrung tage:` | Wie lange Werte pro Mitglied gespeichert bleiben (7–730 Tage) | Admin |

---

## `/automod` — AutoMod (`automod`-Cog, eigener Tab in der Oberfläche)

Alles zu AutoMod an einer Stelle:

1. **Discords eigener AutoMod** (Regeln in Discord unter Servereinstellungen →
   Sicherheit): blockiert er eine Nachricht, vergibt der Bot Warn-Punkte je
   Regeltyp – mit der Eskalation aus dem `moderation`-Cog. Früher Teil von
   `moderation`; die bisherigen Einstellungen gelten weiter.
2. **Eigene Regeln**, die Discord nicht kann. Standardmäßig **aus**
   (`/automod aktiv an:True`). Mods, Admins und Server-Administratoren sind immer
   ausgenommen. Bei einem Verstoß: Nachricht löschen, kurzer Hinweis im Kanal,
   optional Warn-Punkte und Timeout. Während einer Flut wird nur einmal pro 30 s bestraft.

Warn-Punkte gibt es nur, wenn der `moderation`-Cog geladen ist (er führt das
Verwarnsystem) – ohne ihn wird nur gelöscht und gemeldet. Alle Meldungen gehen in
den eigenen AutoMod-Alarmkanal.

| Command | Beschreibung | Level |
|---|---|---|
| `/automod status` | Alle Regeln und Einstellungen | Mod |
| `/automod discord an:` | Warn-Punkte, wenn Discords AutoMod eine Nachricht blockiert | Admin |
| `/automod discord_punkte typ: punkte:` | Warn-Punkte je Regeltyp von Discords AutoMod | Admin |
| `/automod aktiv an:` | Eigene Regeln an/aus | Admin |
| `/automod flut an: nachrichten: sekunden:` | Mehr als X Nachrichten in Y Sekunden (Standard 6 in 8 s) | Admin |
| `/automod wiederholung an: anzahl: sekunden:` | Gleiche Nachricht X-mal in Y Sekunden (Standard 3 in 60 s) | Admin |
| `/automod grossbuchstaben an: prozent: mindestlaenge:` | Zu viel Großschrift (Standard ab 70 % bei mind. 12 Buchstaben) | Admin |
| `/automod emojis an: maximal:` | Mehr als X Emojis (Standard 10) | Admin |
| `/automod links modus:` | `aus`, `nur_erlaubte` (Liste unten) oder `alle_sperren`; Discord-Einladungen zählen als `discord.gg` | Admin |
| `/automod link_erlauben domain:` · `link_entfernen domain:` | Erlaubte Domains (gilt mit Subdomains) | Admin |
| `/automod neue_konten tage:` | Hinweis im Alarmkanal, wenn ein jüngeres Konto beitritt (0 = aus) | Admin |
| `/automod aktion loeschen: punkte: timeout_minuten:` | Folgen eines Verstoßes (Standard: nur löschen) | Admin |
| `/automod alarmkanal kanal:` | Kanal für alle AutoMod-Meldungen (eigene Regeln und Discords AutoMod) | Admin |
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

---

## News der Community-Seite (`news`-Cog, Tab *News*)

Veröffentlichte News mit Haken „In Discord ankündigen“ landen als Embed (Titel,
Anrisstext, Titelbild, Link zur Seite) im News-Kanal; optional wird beim ersten
Posten eine Rolle angepingt. Bearbeiten auf der Seite aktualisiert die Nachricht,
Löschen, Entwurf oder Haken weg entfernt sie. Kanal und Rolle stellst du im Tab
*News* ein – dort lassen sich ältere News auch von Hand posten. Ist der Kanal ein
**Ankündigungskanal**, veröffentlicht der Bot die Nachricht gleich mit, damit sie
auch bei folgenden Servern ankommt (Discord erlaubt etwa 10 pro Stunde und Kanal).
Braucht die angebundene Community-Seite.

| Command | Beschreibung | Level |
|---|---|---|
| `/news` | Die fünf neuesten News mit Links | Member |

---

## Events der Community-Seite (`events`-Cog, Tab *Events*)

Events mit Haken „In Discord ankündigen“ erscheinen im Event-Kanal: Termin (in
der Zeitzone jedes Lesers), Ort, Beschreibung, Teilnehmerzahlen und die Namen der
Zusagen – mit den Knöpfen **Dabei / Vielleicht / Nicht dabei**. Zusagen gelten auf
der Seite, deshalb nur mit verknüpftem Konto (sonst kommt ein Hinweis) und mit
denselben Regeln: Rang braucht das Recht zum Zusagen, das Limit zählt nur feste
Zusagen, keine Zusagen für abgesagte oder vergangene Events. Dieselbe Antwort
nochmal klicken nimmt sie zurück. Änderungen, Zusagen auf der Seite und Absagen
werden nachgezogen.

Optional legt der Bot zusätzlich ein **natives Discord-Event** an (Event-Bereich
des Servers) und zieht Änderungen/Absagen nach – dafür braucht die Bot-Rolle das
Recht **Events verwalten**. Kanal, Ping-Rolle und natives Event stellst du im Tab
*Events* ein; bestehende Events lassen sich dort von Hand posten. In einem
Ankündigungskanal wird die Nachricht wie bei den News veröffentlicht.

| Command | Beschreibung | Level |
|---|---|---|
| `/events` | Die nächsten fünf Events mit Termin und Link | Member |

---

## Tickets der Community-Seite (`tickets`-Cog, Tab *Tickets*)

Voll gespiegelt zwischen Seite und Discord:

- Jedes Ticket bekommt einen **Thread im Staff-Kanal** (Textkanal oder Forum). Die
  Startnachricht zeigt Status, Kategorie, Mitglied und Zuständigen und hat die Knöpfe
  **Übernehmen**, **Schließen**, **Wieder öffnen**.
- **Je Kategorie** lässt sich im Tab ein eigenes Forum und ein eigener Ping festlegen –
  z.B. „Spieler melden“ in ein Forum nur für die Moderation, „Gameserver“ zu den
  Schmieden. Wer Tickets einer Kategorie bearbeiten darf, regelt die Seite: Support
  (`ticket.manage`), Meldungen (`ticket.reports`), Gameserver (`ticket.server`),
  Rollenanfragen (`ticket.roles`).
- Im **Forum** bekommt jeder Beitrag einen Status-Tag (Offen, In Bearbeitung,
  Wartet auf Antwort, Geschlossen) und einen Kategorie-Tag, filterbar im Forum.
  Fehlende Tags legt der Bot an, wenn er dort **Kanäle verwalten** darf – sonst
  nutzt er nur gleichnamige Tags, die das Team selbst angelegt hat. Eigene Tags
  des Teams bleiben am Beitrag stehen.
- Alles aus dem Verlauf der Seite erscheint im Thread (interne Notizen mit 🔒,
  Statuswechsel als Systemzeile). Was der Support im Thread schreibt, landet als
  Antwort auf der Seite; eine Nachricht, die mit `!intern` beginnt, wird interne
  Notiz. ✅/🔒 als Reaktion = übertragen.
- Das Mitglied bekommt Antworten des Supports und das Schließen **per DM** – mit
  einem Knopf **Antworten**, der direkt ins Ticket schreibt.
- Regeln wie auf der Seite: Antwortet der Support, wartet das Ticket auf das
  Mitglied; antwortet das Mitglied, ist es wieder offen; wer zuerst antwortet,
  übernimmt. Bearbeiten darf, wer auf der Seite *Tickets verwalten* hat.
- Wer schreibt oder klickt, muss mit der Seite verknüpft sein. Auf der Seite
  gesperrte Konten können über Discord nichts tun.

| Command | Beschreibung | Level |
|---|---|---|
| `/ticket kategorie:` | Öffnet ein Formular für ein neues Ticket (nur verknüpft, max. 3 in 10 min) | Member |

---

## Rang-Sync (`rangsync`-Cog, Tab *Rang-Sync*, nur Owner)

Keine Befehle – läuft im Hintergrund, sobald im Tab eingeschaltet. Pro Rang der
Seite eine Discord-Rolle und eine Richtung (beide / nur Discord → Seite / nur Seite
→ Discord / aus); vorbelegt mit gleichnamigen Discord-Rollen (Member, Mod, Admin), falls vorhanden.

- **Seite → Discord**: Rang auf der Seite geändert oder neu verknüpft → das Mitglied
  bekommt die Rolle seines Rangs, die Rollen der anderen gesyncten Ränge werden
  entfernt (Thrall = keine Rang-Rolle). Andere Rollen bleiben.
- **Discord → Seite**: Rollen eines verknüpften Mitglieds geändert → höchster
  zugeordneter Rang wird auf der Seite gesetzt.
- Der **König** wird nie automatisch vergeben oder geändert. Ihm lässt sich eine
  Discord-Rolle zuordnen – die vergibt und entzieht der Bot nie, erkennt daran aber
  Konflikte beim Verknüpfen. Wer in Discord die König-Rolle hat, dessen Rang auf der
  Seite ändert der Bot ebenfalls nicht.
- **Zusatzrollen** (Migration 010 der Seite, z.B. Support oder Wiki): eigener
  Abschnitt im Tab. Nicht exklusiv – jede Zusatzrolle für sich, „hat sie auf der
  Seite ⇔ hat die Discord-Rolle“. Standard ist **nur Seite → Discord**, weil die
  andere Richtung Rechte auf der Seite vergibt. Beim Verknüpfen nimmt „beide“ nur
  dazu und nie weg. Rang und Zusatzrollen setzt der Bot in einem Schritt. Rechte
  auf der Seite gelten für Rang und Zusatzrollen zusammen – z.B. darf jemand mit
  einer Support-Zusatzrolle Tickets in Discord bearbeiten, ohne den passenden Rang.
  Ändern auf der Seite braucht `INSERT, DELETE` auf `user_extra_roles`
  (docs/community-grants.sql).
- **Konflikt beim Verknüpfen** (Discord sagt anderes als die Seite) → Ticket, nichts
  wird geändert. Ohne jede Rang-Rolle in Discord gibt es keinen Konflikt – dann
  kommt die Rolle von der Seite.
- **Discord-Bann** eines verknüpften Mitglieds → Ticket (im Namen des eingestellten
  Kontos, sonst des ersten Königs). Die Sperre auf der Seite bleibt getrennt.
- Wer Discord verlässt, behält seinen Rang. Die Bot-Rolle muss über den zugeordneten
  Rollen stehen.

---

## Wiki der Community-Seite (`wiki`-Cog)

| Command | Beschreibung | Level |
|---|---|---|
| `/wiki suche: zeigen:` | Sucht in Titel und Text des Wikis, mit Vorschlägen beim Tippen; eine Seite aus der Liste zeigt ihren Anfang mit Link. Sichtbar ist nur, was man auf der Seite lesen dürfte (verknüpft: nach Rang, sonst nur öffentliche Seiten). `zeigen: True` = für alle im Kanal | Member |

---

## AMP-Konten (`ampkonten`-Cog, Tab *AMP-Konten*, nur Owner)

| Command | Beschreibung | Level |
|---|---|---|
| `/amp` | Eigener AMP-Zugang (nur für dich sichtbar): Panel-Adresse, Stand (aktiv mit Benutzer und Rolle, beantragt, gesperrt, keins) und der nächste Schritt – z.B. fehlende Zusatzrolle mit Link zu *Rolle beantragen*, oder wo man ein neues Passwort anfordert; fehlt die Zusatzrolle, gibt es einen Knopf, um sie direkt zu beantragen (Rollenanfrage auf der Seite) | Member |

Mitglieder beantragen auf der Community-Seite unter *Einstellungen →
AMP-Zugang* ein Konto (nur verknüpft). Der Bot legt es an, gibt ihm die AMP-Rolle
ihres Rangs und schickt das Startpasswort per Discord-DM – beim ersten Login muss es
geändert werden. *Passwort vergessen* auf der Seite schickt ein neues. Ändert sich
der Rang (auf der Seite oder über den Rang-Sync), passt der Bot die Rolle an; ein Rang
ohne Zugang sperrt das Konto (nie löschen), ein gelöschtes Konto auf der Seite ebenso.

**Gameserver-Rollen in AMP einrichten** (Tab, Abschnitt „Gameserver-Rollen in AMP“): Der
Bot legt drei gemeinsame Rollen an (Helfer: starten/stoppen/neustarten, Konsole lesen ·
Betreuer: zusätzlich Konsole schreiben, Spieler, Backups, Updates · Admin: zusätzlich
Einstellungen, Dateien, Zeitpläne, Backups löschen) und setzt ihre Rechte am Controller
(Anmelden; für die Spiel-Instanzen aus dem Tab Server „Manage“ sowie die Instanz starten,
stoppen und neustarten; Admins zusätzlich Instanzen anlegen, löschen, umbauen und neu
angelegte selbst verwalten – nie AMP-Versionen hochziehen) und in jeder
Spiel-Instanz. Benutzer- und Rollenverwaltung sowie Audit-Log sind immer verboten. Die
Rechte-Namen sucht er in der Rechte-Liste des jeweiligen AMP; **Prüfen** zeigt das ohne
etwas zu ändern, **Einrichten** braucht Super-Admin-Rechte – bei jedem neuen Gameserver
einmal, der Tab zeigt, welche noch fehlen. Zwei Wege: **mit dem eigenen AMP-Admin-Konto**
anmelden (Benutzer/Passwort im Tab, nur für diesen Vorgang, nie gespeichert; mit
Zwei-Faktor kann es bei mehreren Gameservern scheitern) oder dem AMP-Benutzer des Bots
kurz „Super Admins“ geben. Ein Neustart ist nicht nötig: Für Prüfen und Einrichten meldet
sich der Bot jedes Mal frisch an, die laufenden Verbindungen behalten ihre normalen Rechte.

Optional eine **Voraussetzung**: eine Zusatzrolle der Seite (z.B. für Gameserver-Betreuer).
Ohne sie gibt es keinen Zugang – wer sie verliert, wird gesperrt –, mit ihr bestimmt
weiterhin der Rang die AMP-Rolle.

Fest eingebaut: Der Bot fasst nur Konten an, die er selbst angelegt hat (ist der
Name schon vergeben, hängt er `-<Nr>` an), vergibt nie *Super Admins* oder seine
eigene Rolle, und das Passwort steht nur in der DM. Im Tab: Adresse des Panels für
die DM und Rang → AMP-Rolle (Standard: kein Zugang).

---

## Rollenanfragen der Community-Seite (`rollenanfragen`-Cog, Tab *Rollenanfragen*)

Kein Slash-Befehl. Mitglieder beantragen auf der Seite unter *Einstellungen → Rolle
beantragen* die **nächste Rangstufe** (nie den Rang mit allen Rechten) oder eine
**Zusatzrolle**, mit Begründung. Wer unter dem Standardrang steht, beantragt nichts.
Grenzen: je Rolle eine offene Anfrage, eine pro Tag, höchstens vier pro Woche, nach
einer Ablehnung dieselbe Rolle erst nach sieben Tagen.

Zu jeder Anfrage legt die Seite ein Ticket der Kategorie *Rollenanfrage* an. Der Bot
postet die Anfrage mit **Zustimmen** / **Ablehnen** in den Mod-Log-Kanal und in den
Ticket-Thread. Entscheiden darf:

| Anfrage | Wer |
|---|---|
| Zusatzrolle | Owner – oder ab Mod, wer die Rolle selbst hat; nur für Mitglieder bis zum eigenen Rang |
| Rang | Owner – oder ab Mod, wer auf der Seite über dem beantragten Rang steht |

Nie bei der eigenen Anfrage. „Owner“ = Bot-Stufe Owner, Discord-Administrator oder auf
der Seite alle Rechte. Wer klickt, muss verknüpft sein.

**Zustimmen** vergibt die Rolle auf der Seite; Rang-Sync und AMP-Konten ziehen sofort
nach (z.B. Schmied → AMP-Konto, ein gesperrtes wird wieder aktiv). **Ablehnen** fragt
nach einem Grund. Beides beantwortet und schließt das Ticket (das Mitglied bekommt es
per DM) und steht kurz im Mod-Log. Braucht die Rechte aus `docs/community-grants.sql`
(`role_requests`).

---

## Forum der Community-Seite (`forum`-Cog, Tab *Forum*)

| Command | Beschreibung | Level |
|---|---|---|
| `/forum` | Die neuesten Themen im Forum der Seite (nur für dich sichtbar) | Member |

Neue Themen im Forum der Seite werden im eingestellten Kanal kurz angekündigt: Titel,
Verfasser, Kategorie, Anfang des Texts und ein Knopf **Hier lesen**. Antworten nicht.
Nur Kategorien, die jeder lesen darf – interne Bereiche erscheinen nie in Discord.
Kanal und Ping-Rolle im Tab *Forum*, dort auch ältere Themen von Hand ankündigen.

---

## Server-News: Neustarts, Wartungen, Ausfälle (`servernews`-Cog, Tab *Server-News*)

| Command | Beschreibung | Level |
|---|---|---|
| `/wartung neustart name: start: grund:` | Neustart ankündigen; zur Zeit startet der Bot den Server neu. `start` = Minuten ab jetzt (`15`) oder Uhrzeit (`20:00`) | Mod\* |
| `/wartung plane name: start: dauer: grund:` | Wartung ankündigen; zur Zeit stoppt der Bot den Server | Mod\* |
| `/wartung liste` | Angekündigte Neustarts und Wartungen mit Nummer | Mod\* |
| `/wartung abbrechen nummer:` | Absagen (steht schon eine Meldung im Kanal, kommt „abgesagt“) | Mod\* |
| `/wartung ende name:` | Wartung beenden: startet den Server, danach „läuft wieder“ | Mod\* |

\* Fähigkeit „Gameserver starten/stoppen“ (Standard ab Mod, weitere Rollen im Tab *Einstellungen*).

Meldungen gehen in den Kanal aus dem Tab *Server-News*. Die **Vorlaufzeiten** sind frei
einstellbar (z.B. `60, 15, 5` Minuten); nur die erste Meldung pingt die eingestellte Rolle,
die übrigen erinnern. Zur Zeit: „startet jetzt neu“ bzw. „Wartung hat begonnen“, danach
„läuft wieder“ mit Verbinden-Adresse. Nicht angekündigte Ausfälle werden ohne Ping
gemeldet (abschaltbar).

**AMP-Zeitplan:** Zeit-Trigger in AMP mit Neustart, Update oder Stopp kann der Bot vorher
ankündigen (ausgeführt von AMP). Erst im Tab mit *Zeitpläne lesen* prüfen, ob die Zeiten
stimmen, dann einschalten. Trigger, die auf Ereignisse reagieren (z.B. „Update
verfügbar“), lassen sich nicht vorhersagen – sie erscheinen als nicht angekündigter
Neustart. Der Bot braucht dafür in AMP das Recht `Core.Scheduler.ViewSchedule`; er trägt
es sich selbst ein, wenn sein AMP-Benutzer beim Start kurz *Super Admins* hat.

**Hinweis im Spiel:** Pro Server ein Konsolenbefehl mit `{text}` (z.B. `say {text}`,
`broadcast {text}`), den der Bot bei jeder Meldung zusätzlich schickt. Jedes Spiel macht
das anders – mit *Testen* im Tab prüfen; leer = nur Discord.

