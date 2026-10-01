# WikingerBot in AMP betreiben

Der Bot läuft als eigene AMP-Instanz – nach dem Vorbild der offiziellen
GatekeeperV2-Vorlage. Die Vorlage liegt im Repo
[Daywalker91/AMPTemplates](https://github.com/Daywalker91/AMPTemplates) und wird in AMP
als *Configuration Repository* eingebunden.

## Was die Vorlage macht

| Schritt | Wann | Was passiert |
|---|---|---|
| Update | Button *Update* in AMP | alten Code entfernen, `main` als ZIP von GitHub laden, venv anlegen, `requirements.txt` installieren |
| Start | Button *Start* | AMP schreibt die Einstellungen als `Wikingerbot-main/.env`, dann `python -u -m bot.main` |
| Beim Start im Bot | automatisch | `alembic upgrade head` (abschaltbar), dann Anmeldung bei Discord |
| „Läuft“ | sobald im Log `WikingerBot bereit: angemeldet als …` steht | Status in AMP wechselt auf *Running* |

Alle Einstellungen (Token, Datenbank, AMP-Zugang) sind Eingabefelder in AMP unter
*Configuration → WikingerBot*. Die `.env` muss nicht von Hand angelegt werden.

## Voraussetzungen

- **AMP-Box:** Python **3.11 oder neuer** mit venv (`sudo apt install python3 python3-venv`),
  alternativ die Instanz im Docker-Modus betreiben (Image `cubecoders/ampbase:python-3`).
- **Datenbank:** MariaDB-Datenbank `wikingerbot` + Benutzer, der sich von der AMP-Box aus
  anmelden darf. Firewall: AMP-Box → MariaDB, Port 3306.
- **Discord:** Bot-Token aus dem [Developer Portal](https://discord.com/developers/applications/).
- **AMP-Benutzer für den Bot:** eigenen Benutzer anlegen (nicht den eigenen verwenden), mit
  Rechten zum Starten/Stoppen der Instanzen und für die Konsole.

## Einrichtung

1. **Vorlagen-Repo einbinden:** *Configuration → Instance Deployment → Configuration Repository*
   → `Daywalker91/AMPTemplates:main` hinzufügen → *Fetch latest*.
2. **Instanz anlegen:** *Create Instance* → Anwendung **WikingerBot** wählen.
3. **Einstellungen** in der neuen Instanz unter *Configuration → WikingerBot*:
   - *Discord Bot Token*
   - *Datenbank-Host* (z.B. `10.0.0.107`), Port, Name, Benutzer, Passwort
   - *AMP URL*: `http://127.0.0.1:8080` – im Docker-Modus die IP der AMP-Box
   - *AMP Benutzer* / *AMP Passwort*
4. **Update** klicken (lädt den Bot und installiert alles), danach **Start**.
5. In der **Konsole** prüfen:
   ```
   INFO    [wikingerbot] Datenbank-Migrationen werden ausgefuehrt ...
   INFO    [wikingerbot] Datenbank ist aktuell.
   INFO    [wikingerbot] WikingerBot bereit: angemeldet als Wikinger#1234 (ID …) auf 1 Server(n)
   ```

## Neue Version einspielen

Änderungen nach `main` pushen → in AMP **Update** → **Restart**. Migrationen laufen beim
Start automatisch. Tipp: In AMP unter *Schedule* einen nächtlichen Update+Restart anlegen.

## Häufige Fehler

| Meldung in der Konsole | Ursache |
|---|---|
| `Kein Discord-Token gesetzt` | Feld *Discord Bot Token* leer |
| `Discord hat den Token abgelehnt` | Token falsch oder im Developer Portal zurückgesetzt |
| `Can't connect to MySQL server` / Timeout | Firewall/IP falsch oder MariaDB nicht erreichbar |
| `Access denied for user` | DB-Benutzer/Passwort falsch oder Benutzer darf sich von dieser IP nicht anmelden |
| Instanz bleibt auf *Starting* | Bot nicht bei Discord angemeldet – Konsole auf Fehler prüfen |

Die Log-Zeile `WikingerBot bereit: …` (in `bot/core/bot.py`) nur zusammen mit
`Console.AppReadyRegex` in der Vorlage ändern, sonst erkennt AMP den Start nicht mehr.
