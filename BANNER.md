# WikingerBot — Banner-Anleitung

Der `banner`-Cog postet pro Server (oder pro Server-Gruppe) eine Nachricht,
die sich automatisch alle 60 Sekunden aktualisiert und den aktuellen Status
zeigt: online/offline, Spielerzahl, Verbindungs-Adresse, Uptime. Diese Seite
erklärt die Optionen im Detail — die reine Befehlsliste steht in
[COMMANDS.md](COMMANDS.md#banner--status-banner-pro-server-banner-cog).

---

## 1. Erste Schritte

```
/banner enable name:<server> channel:#status type:embed
```

Das war's — der Bot postet sofort einen ersten Banner in `#status` und
aktualisiert ihn danach alle 60s per Bearbeiten derselben Nachricht (kein
Zuspammen des Kanals mit neuen Posts).

`type` legt fest, wie der Banner aussieht:

| Typ | Aussehen |
|---|---|
| `embed` | Discord-Embed mit Feldern (Status, Spieler, Uptime, Whitelist). Leichtgewichtig, immer lesbar, kein Hintergrundbild. |
| `image` | Ein von uns gerendertes PNG (800×300px) mit Verlauf/Artwork als Hintergrund, Text mit Schlagschatten darüber. Optisch aufwendiger, unterstützt Themes/eigene Bilder/Steam-Artwork. |

In beiden Fällen steht die Verbindungs-Adresse **zusätzlich** als eigener,
antippbarer/kopierbarer Text über der eigentlichen Nachricht — das ist bei
Bildern der einzige Weg, die Adresse kopierbar zu machen (Pixel lassen sich
nicht markieren).

Später wechseln: `/banner type name:<server> type:image` (postet neu).

---

## 2. Hintergrund der Bild-Variante

Nur relevant für `type:image`. Es gibt vier mögliche Quellen, in dieser
Rangfolge (die höchste greift, wenn mehrere gleichzeitig "gesetzt" sind):

1. **Eigenes hochgeladenes Bild** — `/banner background name:<server> image:<Datei>`
   (PNG/JPEG/WebP, max. 8 MB). Wird zentriert auf 800×300 zugeschnitten.
2. **Automatisch erkanntes Steam-Artwork** — falls AMP für diese Instanz
   eine Steam-App-ID kennt (`Server.steam_app_id`, wird beim Anlegen des
   Servers automatisch aus AMPs `DisplayImageSource` übernommen, siehe
   `/server steam_appid` zum manuellen Nachtragen/Korrigieren), wird das
   offizielle Steam-Store-Titelbild geladen und lokal gecacht.
3. **Eigene Verlaufsfarben** — im Customize-Editor gesetzt (siehe unten).
4. **Eingebautes Theme** — `/banner theme name:<server> theme:<...>`:
   `midnight` (dunkelblau), `forest` (grün), `sunset` (rot/pink), `ocean`
   (blau/violett). Standard, falls nichts anderes gesetzt ist: `midnight`.

`/banner theme` und `/banner background` löschen sich beim Setzen
gegenseitig (immer nur eine der beiden Quellen aktiv), Steam-Artwork bleibt
davon unberührt, da es aus dem separaten `steam_app_id`-Feld kommt.

---

## 3. Customize-Editor (Farben/Schriftfarbe + Unschärfe)

```
/banner customize name:<server>
```

Öffnet eine nur für dich sichtbare Nachricht mit Live-Vorschau und
Auswahlmenüs. Der Editor merkt sich, ob gerade ein Hintergrundbild aktiv ist
(Upload oder Steam-Artwork) und zeigt je nachdem unterschiedliche Optionen:

- **Ohne Hintergrundbild** (Theme aktiv): Start- und Endfarbe des Verlaufs
  wählbar (aus einer Preset-Liste, u.a. Weiß/Schwarz/Mitternachtsblau/
  Waldgrün/Gold/... — Discord kennt keinen freien Colorpicker in
  Slash-Commands). Übernehmen ersetzt das Theme durch diesen eigenen
  Verlauf.
- **Mit Hintergrundbild**: Start-/Endfarbe wären unsichtbar (das Bild hat
  Vorrang), stattdessen gibt's eine **Schriftfarbe**-Auswahl für den Text,
  der über dem Bild liegt.
- **Unschärfe** (immer verfügbar): `Kein` / `Leicht` / `Mittel` / `Stark` —
  weichzeichnet den Hintergrund (Bild oder Verlauf), damit der Text
  unabhängig vom Motiv gut lesbar bleibt.

Buttons: **Vorschau** (rendert neu, ohne zu speichern), **Übernehmen**
(speichert + aktualisiert den echten Banner sofort), **Abbrechen** (verwirft
alles, ohne etwas zu ändern).

---

## 4. Badges

Jeder Banner zeigt unten rechts (Bild) bzw. als eigenes Feld "Whitelist"
(Embed):
- 🔒 gefolgt von der Anzahl genehmigter Whitelist-Anfragen für diesen Server
- ⭐ zusätzlich, falls mindestens einer der freigeschalteten Nutzer als
  Donator markiert ist (`/whitelist donator user:<...> enabled:True`)

---

## 5. Mehrere Server in einem Banner (Banner-Gruppen)

```
/bannergroup create name:"Alle Server" channel:#status type:image layout:combined
/bannergroup add group:"Alle Server" server:<server1>
/bannergroup add group:"Alle Server" server:<server2>
```

Ein Server kann zu maximal einer Gruppe gehören (max. 6 Mitglieder); beim
Hinzufügen wird sein individueller Banner automatisch deaktiviert.

Zwei Layouts (`/bannergroup layout group:<...> layout:<...>` zum
nachträglichen Wechseln):

- **`combined`** (Standard): **ein** gestapeltes Bild bzw. **ein** Embed mit
  gemeinsamem Hintergrund/Theme/Farben/Unschärfe für die ganze Gruppe;
  jedes Mitglied bekommt darin ein kompaktes Panel. Die gruppenweiten
  Befehle `/bannergroup theme` / `background` / `customize` wirken hier.
- **`separate`** (wie GatekeeperV2s Banner Groups): jedes Mitglied bekommt
  sein **eigenes** vollständiges Banner-Bild/-Embed — mit seinem **eigenen**
  Steam-Artwork/Theme/Farben, exakt wie ein Einzel-Banner — alle zusammen
  als mehrere Anhänge/Embeds in **einer** Nachricht. Die gruppenweiten
  `theme`/`background`/`customize`-Befehle wirken hier **nicht**, da jedes
  Mitglied seine eigene Optik behält (dafür `/banner theme` usw. direkt am
  Mitgliedsserver nutzen, auch wenn er in einer Gruppe steckt).

Faustregel: `combined` für "ein einheitliches Server-Status-Board", `separate`
wenn jeder Server sein eigenes, individuelles Artwork behalten soll.

---

## 6. Troubleshooting

- **"Nicht erreichbar" im Banner** heißt: der `Core.GetStatus()`-Aufruf an
  AMP ist fehlgeschlagen (Server wirklich offline, AMP-Instanz falsch
  konfiguriert, Netzwerkproblem) — kein Banner-Bug, sondern eine ehrliche
  Fehlermeldung.
- **Banner aktualisiert sich nicht**: Die Update-Loop läuft alle 60s. Bei
  wiederholten Fehlschlägen (z.B. ein hängendes Discord-Rate-Limit) wartet
  sie mit steigender Pause (60s → 120s → 240s → ... bis max. 30 Min.), statt
  stur jede Minute erneut anzurennen — das behebt sich von selbst, sobald
  das zugrunde liegende Problem weg ist. `/banner refresh` bzw.
  `/bannergroup refresh` erzwingt sofort einen neuen Versuch.
- **Neue Slash-Commands fehlen nach einem Bot-Update**: `/bot sync
  local:True` ausführen (siehe [COMMANDS.md](COMMANDS.md)).
