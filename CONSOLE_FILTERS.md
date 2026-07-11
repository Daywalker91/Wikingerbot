# WikingerBot — Konsolen-Filter & Event-Erkennung

Der `amp`-Cog spiegelt die AMP-Konsole eines Servers in einen Discord-Kanal.
Manche Spiele spammen dabei ständig unwichtige Zeilen (z.B. alle paar
Sekunden "Saved X map points to disk"), während andere Zeilen interessant
sind (Spieler betritt/verlässt den Server). Diese Seite erklärt, wie man das
steuert — die Befehlsliste steht in [COMMANDS.md](COMMANDS.md#server--amp-serververwaltung-amp-cog).
Da das Ganze auf **Regex** (regulären Ausdrücken) basiert und nicht jeder
damit vertraut ist, erklärt diese Seite auch die Grundlagen davon.

---

## 1. Die drei Filter-Modi

`/server console_filter_mode name:<server> mode:<...>`

| Modus | Verhalten |
|---|---|
| `off` | Alles wird durchgelassen, keine Unterdrückung. |
| `blacklist` (Standard) | Zeilen, die auf ein Filter-Muster passen, werden **unterdrückt** (nicht gepostet). Alles andere kommt durch. Gut, wenn nur wenige, bekannte Zeilen nerven. |
| `whitelist` | Nur Zeilen, die auf ein **eigenes** Muster passen, kommen durch — alles andere wird unterdrückt. Die eingebauten Muster zählen hier nicht (sie sind als "das ist Rauschen"-Liste gedacht, nicht als "das ist erlaubt"-Liste). Gut, wenn eine Konsole so extrem spammt, dass es einfacher ist zu sagen, was man sehen will, statt was nicht. |

**Event-Erkennung hat immer Vorrang**: Eine Zeile, die wie ein Join/Leave
aussieht, geht auch dann in den Event-Kanal, wenn sie zufällig auch ein
Filter-Muster trifft.

---

## 2. Regex-Grundlagen (kurz)

Ein "regulärer Ausdruck" (Regex) ist ein Suchmuster für Text — mächtiger als
einfaches "kommt dieser Text vor", weil man Platzhalter benutzen kann.
Alles, was in unseren Mustern wichtig ist:

| Zeichen | Bedeutung | Beispiel |
|---|---|---|
| (normaler Text) | muss genau so vorkommen | `joined` passt auf jede Zeile, die irgendwo "joined" enthält |
| `\d` | eine einzelne Ziffer (0-9) | `\d+` = "eine oder mehrere Ziffern", passt auf `42`, `1337` |
| `\s` | ein Leerzeichen/Tab | `\s+` = "ein oder mehrere Leerzeichen" |
| `\b` | Wortgrenze (verhindert Teiltreffer) | `\bleft\b` passt auf "left" aber nicht auf "shellfish" |
| `.` | ein beliebiges Zeichen | `A.C` passt auf "ABC", "A1C", ... |
| `+` | das Vorherige 1x oder öfter | `\d+` s.o. |
| `*` | das Vorherige 0x oder öfter | |
| `?` | das Vorherige optional (0 oder 1x) | |
| `^` | Anfang der Zeile | `^Connections` passt nur, wenn die Zeile damit **beginnt** |
| `$` | Ende der Zeile | |
| `\|` | ODER | `joined\|connected` passt auf beides |

Wichtig zu wissen:
- **Groß-/Kleinschreibung spielt keine Rolle** — unsere Muster ignorieren
  das automatisch (`joined` passt auch auf "Joined" oder "JOINED").
- Ein Muster muss nicht die **ganze** Zeile beschreiben — es reicht, wenn es
  **irgendwo** in der Zeile vorkommt (außer man verankert es explizit mit
  `^`/`$`).
- Sonderzeichen wie `.`, `(`, `)`, `[`, `]` haben in Regex eine besondere
  Bedeutung. Will man sie wörtlich meinen, mit `\` davor escapen (z.B. `\.`
  für einen echten Punkt). `/server pattern_add` prüft dein Muster beim
  Speichern (`re.compile`) und meldet einen Fehler, falls es ungültig ist.

**Testen**: Es gibt keinen Trockentest-Befehl — am einfachsten ein Muster
hinzufügen, kurz den Konsolen-/Event-Kanal beobachten, ob es wie erwartet
greift, und bei Bedarf mit `/server pattern_remove` wieder entfernen.

---

## 3. Eingebaute Muster

Diese sind im Bot-Code hinterlegt (`bot/core/console_filters.py`), gelten
für alle Server und lassen sich pro Server einzeln abschalten (siehe
Abschnitt 4) — die Zeile selbst kann man nicht ändern, nur an/aus.

**Filter (Rauschen, `blacklist`-Modus)**

| Key | Muster | Beispiel-Zeile, die es trifft |
|---|---|---|
| `map_points_saved` | `Saved \d+ map points to disk` | `Saved 6840 map points to disk.` (Valheim) |
| `zdos_connections` | `^Connections \d+ \S+\s+sent:\d+ recv:\d+` | `Connections 3 192.168.1.5 sent:1024 recv:2048` (Valheim ZDO-Debug-Zeilen) |

**Event (Join/Leave-Erkennung, immer aktiv unabhängig vom Filter-Modus)**

| Key | Muster | Erkennt z.B. |
|---|---|---|
| `joined` | `\bjoined\b` | "Steve123 joined the game" |
| `connected` | `\bconnected\b` | "Player connected from 1.2.3.4" |
| `entered` | `\bhas entered\b` | "Steve123 has entered the server" |
| `left` | `\bleft the game\b` | "Steve123 left the game" |
| `disconnected` | `\bdisconnected\b` | "Player disconnected" |
| `has_left` | `\bhas left\b` | "Steve123 has left" |
| `logged_in` | `\blogged in\b` | "Steve123 logged in" |
| `logged_out` | `\blogged out\b` | "Steve123 logged out" |

---

## 4. Eigene Befehle

- **Eigenes Muster hinzufügen**:
  `/server pattern_add name:<server> kind:<filter|event> pattern:<regex>`
  — z.B. ein Muster, das eine besonders nervige, spielspezifische Zeile
  erfasst, die die eingebauten Muster nicht abdecken (kam beim Testen mit
  Valheim vor: `Connections \d+ ZDOS` als eigenes Filter-Muster, weil das
  eingebaute `zdos_connections`-Muster ein anderes Zeilenformat erwartete).
- **Eigenes Muster entfernen**: `/server pattern_remove name:<server>
  pattern_id:<ID>` (die ID steht in `/server pattern_list`).
- **Eingebautes Muster für einen Server abschalten**: `/server
  pattern_toggle name:<server> kind:<filter|event> key:<Key aus der Tabelle
  oben> enabled:False` (z.B. `key:map_points_saved` abschalten, wenn man
  diese Zeilen doch sehen will).
- **Alles ansehen**: `/server pattern_list name:<server>
  kind:<filter|event>` zeigt eingebaute Muster (mit Status aktiv/inaktiv)
  und eigene Muster mit ihrer ID.

---

## 5. Beispiel-Rezepte

| Ziel | Befehl |
|---|---|
| Eine bestimmte, wiederkehrende Zeile ausblenden | `/server pattern_add kind:filter pattern:"Autosave abgeschlossen"` |
| Nur Zeilen mit "ERROR" oder "WARNING" durchlassen | Modus auf `whitelist` stellen, dann `/server pattern_add kind:filter pattern:"ERROR|WARNING"` |
| Ein Item-Aufsammel-Event als "Event" markieren | `/server pattern_add kind:event pattern:"\bpicked up\b"` |
| Eingebautes Rauschmuster gilt für dieses Spiel nicht | `/server pattern_toggle kind:filter key:map_points_saved enabled:False` |
