# Plan: Mehrere Discord-Server mit je eigener Community-Seite

Stand: 2. Oktober 2026 · noch nicht umgesetzt

## Ziel

Der Bot läuft auf mehreren Discord-Servern. Jeder Server ist mit **seiner** Community-Seite
verbunden; Aufträge, Verknüpfungen, Tickets, Ränge usw. einer Seite landen nur auf den
Servern, die zu ihr gehören.

**Entschieden:**

- Jede Seite hat **eigene Zugangsdaten** (Host, Port, Datenbank, Benutzer, Passwort) – in der
  Bot-Oberfläche einzutragen.
- **Eine Seite kann zu mehreren Discord-Servern gehören** (z.B. Haupt- und Event-Discord).
  Ein Discord-Server gehört höchstens zu einer Seite.

## Was schon heute pro Server funktioniert

Diese Cogs speichern alles mit der Server-ID und brauchen **keine Änderung**: `amp` (Server,
Konsole), `banner`, `whitelist`, `moderation`, `automod`, `welcome`, `roles`, `music`, `stats`,
`admin`. Ebenso die Zuordnung „welche Discord-Nachricht gehört zu welchem Beitrag“
(`community_posts`, Spalte `guild_id`) und alle Einstellungen in `guild_config`.

Die Seiten selbst (PHP) brauchen **keine Änderung**.

## Was heute von „genau einer Seite“ ausgeht

| Stelle | Heute | Künftig |
|---|---|---|
| `bot/community/db.py` | eine globale Verbindung (`session()`, `enabled()`, `site_link()`) | Register mehrerer Seiten: `site_for_guild(guild_id)`, `session(site)`, `site.link(...)` |
| Einstellungen | `bot_settings`: `community_db_name`, `community_site_url` | Tabellen `community_sites` und `community_site_guilds` |
| `bot/community/outbox.py` | holt Aufträge der einen Seite | holt pro Seite; Handler bekommen `(site, payload)` |
| News, Events, Tickets (`sync_*`) | durchlaufen `bot.guilds` | nur die Server der Seite (`site.guild_ids`) |
| `bot/community/linking.py` | Discord-Konto ↔ ein Seitenkonto | pro Seite (dasselbe Discord-Konto kann auf A und B verknüpft sein) |
| Befehle `/verknuepfen`, `/profil`, `/ticket`, `/wiki`, `/news`, `/events`, `/community status` | die eine Seite | Seite des Servers, auf dem der Befehl kommt (`interaction.guild_id`) |
| Knöpfe in Server-Kanälen (Zusagen, Ticket-Aktionen) | die eine Seite | Seite über `interaction.guild_id` |
| Knopf „Antworten“ in Ticket-DMs | `wb:ticketreply:<ticket>` | `wb:ticketreply:<site>:<ticket>` (in DMs gibt es keinen Server); alte Form als Rückfall |
| `rangsync` | eine Seite | Seite des Servers; Zuordnung bleibt pro Server |
| `ampkonten` | `amp_accounts.site_user_id` eindeutig, eine Rang→Rolle-Zuordnung | Schlüssel `(site_id, site_user_id)`, Zuordnung pro Seite; AMP-Panel bleibt gemeinsam |
| `system_tickets` | eine Seite | Seite als Parameter |
| Tabs der Oberfläche (Community, News, Events, Tickets, Rang-Sync, AMP-Konten) | eine Seite | Seite des eingeloggten Servers (`user.guild_id`) |

Betroffen sind rund 20 Dateien, alle im Community-Teil (`bot/community/`, `bot/cogs/{community,news,events,tickets,rangsync,wiki,ampkonten}`).

## Datenmodell (Bot-Datenbank, Alembic)

```text
community_sites
  id            PK
  name          Anzeigename ("Wikinger")
  db_host       NULL = DB_* aus AMP verwenden
  db_port
  db_name
  db_user       NULL = DB_* aus AMP
  db_password   verschlüsselt (Fernet), NULL = DB_* aus AMP
  site_url      https://...
  created_at

community_site_guilds
  guild_id      PK  (FK guilds)   -- ein Server -> höchstens eine Seite
  site_id       FK community_sites

amp_accounts
  + site_id     Teil des Primärschlüssels (site_id, site_user_id)

community_posts      -- unverändert (schon pro guild_id)
```

Passwörter werden mit einem Schlüssel aus `data/community_key` verschlüsselt (wird wie
`data/jwt_secret` beim ersten Start erzeugt und bleibt bei Updates erhalten). Die Oberfläche
gibt Passwörter nie zurück, nur „gesetzt / nicht gesetzt“.

## Übernahme des heutigen Stands (ohne Zutun)

Beim ersten Start nach dem Umbau, falls noch keine Seite existiert und `community_db_name`
gesetzt ist:

1. Seite „Community“ anlegen – ohne eigene Zugangsdaten (nutzt `DB_*` aus AMP wie heute),
   Datenbank und Adresse aus den alten Einstellungen.
2. Alle Server, auf denen der Bot gerade ist, dieser Seite zuordnen.
3. `amp_accounts` bekommen `site_id` dieser Seite; die Rang→AMP-Rolle-Zuordnung wird ihr zugeordnet.

Verknüpfungen, Tickets, Zusagen usw. liegen auf der Seite selbst – sie bleiben, wie sie sind.

## Ablauf in Schritten

1. **Kern** – `community_sites`/`community_site_guilds`, Verschlüsselung, Register der
   Verbindungen (`site_for_guild`, `session(site)`, Verbindung je Seite, Neuverbinden bei
   Änderung), Übernahme des heutigen Stands. Tests: zwei Seiten, zwei Server, Zuordnung.
2. **Outbox** pro Seite abholen, Handler-Signatur `(site, payload)`; alle Handler umstellen.
3. **Cogs** umstellen: community, news, events, tickets, rangsync, wiki, ampkonten,
   system_tickets – überall die Seite aus dem Server bzw. dem Auftrag; Schleifen über
   `bot.guilds` → `site.guild_ids`.
4. **Knöpfe**: Ticket-DM-Knopf mit Seiten-ID; Rückfall für alte Knöpfe.
5. **Oberfläche**: Tab *Community* pro Server – Seite wählen oder neu anlegen
   (Name, Host, Port, Datenbank, Benutzer, Passwort, Adresse, „Zugangsdaten aus AMP“),
   Verbindung prüfen, Server zuordnen/lösen; zusätzlich „SQL für die Rechte dieser Seite
   anzeigen“ (Grants mit dem eingetragenen Benutzer). Die übrigen Tabs nehmen die Seite des
   eingeloggten Servers.
6. **Tests** für alles mit zwei Seiten: Aufträge von Seite A erreichen nur die Server von A,
   Verknüpfung auf A gilt nicht auf B, Knöpfe/DMs landen bei der richtigen Seite.
7. **Doku**: `AMP.md`, `COMMANDS.md`, `README.md`.

## Offene Detailfragen (vor dem Start klären)

- **Rang-Sync bei einer Seite mit mehreren Servern:** Discord → Seite von *jedem* zugehörigen
  Server oder nur von einem „Haupt-Server“? (Sonst kann eine Rollenänderung auf dem
  Event-Discord den Rang auf der Seite ändern.) Vorschlag: pro Server einstellbar, Standard
  „nur Seite → Discord“ für weitere Server.
- **AMP-Konten bei mehreren Seiten:** gleiches AMP-Panel für alle Seiten (Vorschlag) – oder
  pro Seite ein eigenes AMP? Letzteres wäre ein eigener, größerer Umbau.
- **Tickets bei mehreren Servern einer Seite:** Thread in jedem Server mit Staff-Kanal
  (heute so) oder nur in einem? Vorschlag: so lassen, jeder Server mit Staff-Kanal bekommt
  den Thread.
- **Login in die Oberfläche:** bleibt pro Server (wie heute, mit Auswahl beim Login).
