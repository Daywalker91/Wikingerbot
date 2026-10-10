# Plan: Zusatzrollen auf der Community-Seite und Sync mit Discord

Stand: **umgesetzt** (Oktober 2026). Abweichung vom Plan: statt einer Datenbank-View
`user_permissions` gibt es eine gemeinsame Unterabfrage (Seite: `user_permissions_sql()`,
Bot: `community_db.permissions_subquery()`) – so braucht weder die Seite das Recht
CREATE VIEW noch der Bot Rechte auf eine View. Ohne Leserecht auf `user_extra_roles`
rechnet der Bot nur mit dem Rang. Die Strafrolle (Thrall-Punkte unten) heißt im Bot
allgemein `/strafrolle`; welche Rolle es ist, steht im Tab Moderation.
Später entfallen: das Seiten-Recht `gameserver.control` (nie geprüft) – Gameserver steuern
regeln die Bot-Fähigkeit `server.control` und die AMP-Voraussetzung im Tab *AMP-Konten*.

## Ziel

Neben dem **Rang** (genau einer pro Mitglied, gestaffelt, z.B. Thrall < Karl < Huskarl
< Jarl < König) bekommen Mitglieder beliebig viele **Zusatzrollen** für Aufgaben, z.B.:

| Zusatzrolle (Beispiel) | Aufgabe | Rechte auf der Seite |
|---|---|---|
| Heiler | Support | `ticket.manage`, `ticket.create` |
| Skalde | Wiki | `wiki.edit`, `wiki.manage` |
| Chronist | News | `news.manage` |
| Festmeister | Events | `events.manage`, `events.join` |
| Schmied | Gameserver | `gameserver.control` (neu, nur für den Bot) |

- **Rechte eines Mitglieds = Rechte des Rangs ∪ Rechte aller Zusatzrollen.**
- Moderation (Rang) und Support (Zusatzrolle) bleiben getrennt: Ein Mod ist nicht automatisch
  Support und umgekehrt.
- Zusatzrollen werden mit Discord-Rollen synchronisiert (wie der Rang-Sync, aber nicht
  exklusiv: man kann mehrere gleichzeitig haben).
- Der Bot kann einzelne Befehle an Zusatzrollen binden (z.B. Gameserver starten/stoppen für
  Schmiede, ohne Mod zu sein).

## Teil 1: Community-Seite

### Datenmodell (Migration `010_zusatzrollen.php`, idempotent wie 008/009)

Zusatzrollen in derselben Tabelle wie die Ränge, unterschieden über eine Spalte. Damit
funktionieren `role_permissions` und der Rollen-Editor ohne zweite Rechte-Tabelle.

```sql
ALTER TABLE roles ADD COLUMN kind ENUM('rank','extra') NOT NULL DEFAULT 'rank';

CREATE TABLE user_extra_roles (
    user_id     INT UNSIGNED NOT NULL,
    role_id     INT UNSIGNED NOT NULL,
    assigned_by INT UNSIGNED NULL,
    assigned_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, role_id),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (role_id) REFERENCES roles (id) ON DELETE CASCADE
);

-- Eine Stelle fuer "welche Rechte hat ein Mitglied" - Seite UND Bot fragen nur noch diese View
CREATE VIEW user_permissions AS
    SELECT u.id AS user_id, p.permission FROM users u JOIN role_permissions p ON p.role_id = u.role_id
    UNION
    SELECT x.user_id, p.permission FROM user_extra_roles x JOIN role_permissions p ON p.role_id = x.role_id;
```

- `users.role_id` zeigt weiterhin nur auf einen Rang (`kind = 'rank'`); eine Prüfung im Code
  verhindert, dass dort eine Zusatzrolle landet.
- `level` bei Zusatzrollen bestimmt nur, **wer sie vergeben darf** (unter dem eigenen Level,
  König alle), nicht die Rang-Reihenfolge.
- Die Migration legt die Beispielrollen oben an (abschaltbar/umbenennbar im Admin-Bereich).
- Neues Recht in `PERMISSIONS`: `gameserver.control` – „Gameserver starten/stoppen und
  Konsole (Discord-Bot)“. Die Seite selbst nutzt es nicht, es ist für den Bot.

### Code-Stellen

- `src/auth.php`: Rechte des angemeldeten Benutzers aus `user_permissions` laden statt nur
  über `role_id`. `can()` bleibt unverändert.
- Alle SQL-Abfragen, die heute `role_permissions` über `u.role_id` joinen, auf die View
  umstellen: `src/account.php`, `src/tickets.php` (Staff-Liste/Zuständige), `src/events.php`,
  `src/forum.php`, `src/news.php`, `src/wiki.php`, `pages/members.php`, `pages/tickets/*` u.a.
  (vorher per grep vollständig erfassen).
- `pages/admin/roles.php` / `role.php`: zwei Abschnitte **Ränge** und **Zusatzrollen**;
  Zusatzrollen anlegen, umbenennen, Farbe/Icon, Rechte, löschen.
- `pages/admin/user.php`: Rang wie bisher, darunter Zusatzrollen als Häkchen (nur die, die man
  vergeben darf). Jede Änderung schreibt `user.extra_roles` in den `bot_outbox`.
- Profil, Mitgliederliste, Forenbeiträge: Zusatzrollen als kleine Abzeichen neben dem Rang.
- Ticket-Ansicht: „Zuständig“ zeigt alle mit `ticket.manage` (kommt automatisch über die View).

## Teil 2: Bot

### Lesezugriff auf die Seite

- `bot/community/db.py`: `roles.kind`, `user_extra_roles` und die View `user_permissions`
  als Core-Tables.
- Die vier Stellen, die heute Rechte über `users.role_id` joinen, auf die View umstellen:
  `tickets/site.py` (`is_staff`, `has_permission`), `events/posting.py`,
  `rangsync/api.py` (`_staff_candidates`), `community/system_tickets.py`. Damit dürfen
  z.B. Heiler ohne passenden Rang Tickets bearbeiten.
- `docs/community-grants.sql`: `SELECT` auf `user_extra_roles` und `user_permissions`,
  `SELECT, INSERT, DELETE` auf `user_extra_roles` nur falls Discord → Seite erlaubt wird.

### Sync Zusatzrolle ↔ Discord-Rolle (im Rang-Sync-Cog, eigener Abschnitt im Tab)

Tab **Rang-Sync** bekommt einen zweiten Abschnitt **Zusatzrollen**:

| Zusatzrolle | Discord-Rolle | Richtung |
|---|---|---|
| Heiler | @Heiler | nur Seite → Discord (Standard) / beide / aus |

- **Nicht exklusiv:** pro Zusatzrolle gilt nur „hat sie ⇔ hat die Discord-Rolle“; andere
  Rollen bleiben unberührt (anders als beim Rang, wo die Rolle des alten Rangs entfernt wird).
- **Seite → Discord:** Outbox `user.extra_roles`, beim Verknüpfen, bei „Jetzt abgleichen“.
- **Discord → Seite:** nur wenn ausdrücklich „beide“ gewählt; vergibt Rechte auf der Seite,
  daher Standard aus. Beim Verknüpfen wird nie still etwas geändert: weichen Seite und
  Discord ab, gibt es wie beim Rang ein Konflikt-Ticket.
- Gespeichert in `guild_config` (`rangsync_extra_map`), Discord-IDs als Text (Snowflake).
- Tests wie `tests/test_rangsync.py`: hinzufügen, entfernen, mehrere gleichzeitig,
  Richtung „aus“, Konflikt beim Verknüpfen.

### Befehle an Rollen binden (Zusatz-Berechtigungen)

Heute sind die Bot-Stufen streng gestaffelt (Member < Mod < Admin < Owner). Neu: einzelne
**Fähigkeiten**, die zusätzlich zur Stufe auch bestimmte Discord-Rollen haben dürfen.

| Fähigkeit | Befehle / Tabs | Standard-Stufe | zusätzlich z.B. |
|---|---|---|---|
| `server.control` | `/server start`, `stop`, `console`, Start/Stop/Konsole im Tab Server | Mod | @Schmied |
| `whitelist.review` | Annehmen/Ablehnen, `/whitelist list`, `approve`, `deny` | Mod | @Heiler |
| `banner.refresh` | `/banner refresh`, `/bannergroup refresh` | Mod | @Schmied |
| `music.control` | Steuern ohne im Kanal zu sein, `/musik url` | Mod | – |

- `bot/core/permissions.py`: `require_capability("server.control", Level.MOD)` – erlaubt,
  wenn Stufe ≥ Standard **oder** eine der zugeordneten Rollen vorhanden ist. Gleiche Logik
  für die API (`require_capability` als FastAPI-Dependency) und für Knöpfe.
- Zuordnung im Tab **Einstellungen**, neuer Abschnitt „Zusatz-Berechtigungen“
  (Fähigkeit → Discord-Rollen, Mehrfachauswahl), gespeichert in `guild_config`.
- Optional: Fähigkeit statt Discord-Rolle an ein Recht der Seite binden
  (z.B. `gameserver.control`) – greift dann nur für verknüpfte Mitglieder.

## Verwandte offene Punkte (Thrall)

Am selben Ort sinnvoll, weil es um Rollen und Strafen geht:

1. **Lücke beim Wiederbeitritt:** Wer als Thrall geht und wiederkommt, bekäme per Autorole
   wieder Karl. Lösung: verknüpft → beim Beitritt Rang der Seite statt Autorole; nicht
   verknüpft → Bot merkt sich Thrall beim Verlassen und vergibt es beim Wiederbeitritt.
2. **`/thrall mitglied: grund:` und `/thrall aufheben`** (Mod): stuft herab, Modlog-Eintrag,
   bei verknüpften Mitgliedern auch der Rang auf der Seite.
3. **Eskalationsstufe „Thrall“** in der Warn-Leiter der Moderation.

## Reihenfolge

1. Seite: Migration, View, `auth.php`, alle Rechte-Abfragen auf die View, Admin-UI.
   Ohne Bot-Änderung lauffähig (der Bot liest bis dahin weiter nur den Rang).
2. Grants für den Bot ergänzen.
3. Bot: Rechte-Abfragen auf die View → Heiler können sofort Tickets bearbeiten.
4. Bot: Sync Zusatzrolle ↔ Discord-Rolle im Rang-Sync-Tab.
5. Bot: Zusatz-Berechtigungen (Fähigkeiten) in Kern, API und Tab Einstellungen.
6. Thrall-Punkte.
7. Doku: COMMANDS.md, Hilfe-Texte in den Tabs; Teamhilfe-Kanal anpassen.
