# WikingerBot in AMP betreiben

Der Bot läuft als eigene AMP-Instanz – nach dem Vorbild der offiziellen
GatekeeperV2-Vorlage. Die Vorlage liegt im Repo
[Daywalker91/AMPTemplate](https://github.com/Daywalker91/AMPTemplate) und wird in AMP
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
- **AMP-Benutzer für den Bot:** eigenen Benutzer anlegen (nicht den eigenen verwenden) und ihm
  zunächst **Super Admins** geben – der Bot richtet sich beim Start seine eigene Rolle ein
  (siehe unten).

## Einrichtung

1. **Vorlagen-Repo einbinden:** *Configuration → Instance Deployment → Configuration Repository*
   → `Daywalker91/AMPTemplate:main` hinzufügen → *Fetch Latest* → **AMP (ADS) neu starten**
   (neue Vorlagen erscheinen erst nach dem Neustart).
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

## Die AMP-Rolle des Bots

Nach dem Vorbild von GatekeeperV2 richtet sich der Bot seine Rechte selbst ein
(`bot/core/amp_role.py`):

1. Hat der AMP-Benutzer des Bots **Super Admins**, legt der Bot beim Start die Rolle
   **WikingerBot** an – nur mit den Rechten, die er braucht (Instanzen auflisten,
   starten, stoppen, Status, Konsole) – und nimmt sich selbst hinein.
2. Danach gibt er **Super Admins** ab (außer *Super Admin behalten* ist angehakt).
3. Danach darf der Bot Benutzer und Rollen nicht einmal mehr lesen – das ist gewollt. Bei
   späteren Starts steht dann nur „keine Verwaltungsrechte … Pruefung uebersprungen“ im Log.
   Braucht eine neue Bot-Version mehr Rechte, dem Benutzer einmal kurz wieder **Super Admins**
   geben: Der Bot ergänzt die Rolle beim nächsten Start und gibt Super Admin wieder ab.

Ausdrücklich **nicht** enthalten: Benutzer- und Rollenverwaltung, Instanzen anlegen/löschen,
Updates, Dateimanager, Einstellungen, Backups. Im Log stehen alle Schritte unter
`[wikingerbot.amp_role]`.

Die eigene Instanz blendet der Bot überall aus (`/server discover`, Auswahllisten), damit er
sich nicht selbst stoppen kann – erkannt am Pfad `…/instances/<Name>/`, im Docker-Modus über
das Feld *Eigene Instanz*.

## Web-Oberfläche

Die Web-Oberfläche läuft im selben Prozess wie der Bot, auf dem AMP-Port der Instanz
(Standard 8765): Seite unter `/`, API unter `/api`. Das gebaute Frontend lädt die Vorlage beim
Update als `webui.zip` vom Release [`webui`](https://github.com/Daywalker91/Wikingerbot/releases/tag/webui)
(baut eine GitHub Action bei jedem Push) – auf dem AMP-Server ist kein Node.js nötig.

Einrichten:

1. Die Adresse ermittelt der Bot selbst: `/bot web` fragt AMP nach dem Link der Instanz (die
   Vorlage zeigt ihn in AMP als `http://<IP>:<Port>` an), der Login nimmt die Adresse, mit der
   die Seite aufgerufen wurde. **Web-Adresse** nur eintragen, wenn die Oberfläche unter einem
   anderen Namen erreichbar ist (z.B. später eine Domain) – dann gilt sie für beides.
2. Im [Discord Developer Portal](https://discord.com/developers/applications/) unter
   **OAuth2 → Redirects** `<Adresse>/api/auth/callback` eintragen, z.B.
   `http://192.168.4.5:8765/api/auth/callback` – für jede Adresse, über die angemeldet wird.
3. **Client ID** und **Client Secret** (OAuth2-Seite) in AMP eintragen.
4. Port in der Firewall nur freigeben, wenn die Oberfläche von außerhalb erreichbar sein soll.

### https über einen Reverse-Proxy (z.B. Edge-Gateway)

Am Bot ändert sich dafür nichts außer zwei Feldern:

- **Web-Adresse** = die https-Adresse, z.B. `https://bot.wikinger.ipv64.net` (Discord-Redirect
  dann `https://bot.wikinger.ipv64.net/api/auth/callback`).
- **Vertrauenswürdige Proxys** = die Adressen, von denen der Proxy beim Bot ankommt (beim
  Edge-Gateway die DMZ-IPs der k3s-Knoten – nicht die internen aus `kubectl get nodes`). Nur deren `X-Forwarded-*` glaubt der Bot – sonst
  könnte jeder, der den Port direkt erreicht, sich als https ausgeben. Leer = jedem.

Der Proxy muss `X-Forwarded-Proto` setzen und den `Host` durchreichen (Caddy tut beides von
selbst). Das Login-Cookie wird bei https automatisch als `Secure` gesetzt.

Das Signier-Geheimnis für Logins (`JWT_SECRET`) erzeugt der Bot beim ersten Start selbst
(`data/jwt_secret`, bleibt bei Updates erhalten). Angemeldet wird über den Discord-Server,
auf dem der Bot ist; die Seiten zeigen nur, was die eigene Bot-Rolle (Member/Mod/Admin/Owner)
darf.

## Community-Seite anbinden (optional)

Der Bot läuft ohne die Seite. Für die Anbindung (Verknüpfen, News, Events, Tickets …):

1. Auf der Seite läuft die Migration `008_discord` von selbst (beim nächsten Seitenaufruf).
2. Dem Bot-Benutzer der Datenbank eng begrenzte Rechte auf die Datenbank der Seite geben
   (spaltengenau – er sieht z.B. weder E-Mail noch Passwort-Hash). Das SQL dafür steht im
   README der Seite bzw. wurde einmalig bereitgestellt.
3. In AMP unter *Community-Seite*: **Datenbank der Community-Seite** (z.B. `php`) und
   **Adresse der Community-Seite** (z.B. `https://wikinger.ipv64.net`). Host, Benutzer und
   Passwort kommen aus dem Abschnitt *Datenbank*.
4. Neustart. Im Log darf dann **nicht** „Community-Seite nicht angebunden“ stehen;
   `/community status` zeigt, ob die Datenbank erreichbar ist.
5. Erst danach auf der Seite in `config.local.php` `'discord_enabled' => true` setzen – vorher
   würde die Seite Aufträge schreiben, die niemand abholt.

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
