-- Rechte des WikingerBot auf die Datenbank einer Community-Seite.
--
-- Als Administrator (z.B. root) in MariaDB/MySQL ausfuehren, NACHDEM die Seite ihre
-- Migrationen 008_discord und 009_amp_zugang ausgefuehrt hat.
--
-- Vorher ersetzen:
--   <SITE_DB>   Datenbank der Community-Seite, z.B. community
--   <BOT_USER>  Datenbank-Benutzer des Bots, z.B. wikingerbot
--   <BOT_HOST>  Host, von dem der Bot sich anmeldet, z.B. 192.0.2.20 oder '%'
--               (welcher Host eingetragen ist: SELECT user, host FROM mysql.user;)
--
-- Bewusst spaltengenau: Der Bot sieht von den Mitgliedern weder E-Mail noch
-- Passwort-Hash und darf nur die Spalten aendern, die er braucht.

-- Mitglieder: lesen (ohne E-Mail/Passwort), Discord-Verknuepfung, Rang (Rang-Sync), AMP-Stand
GRANT SELECT (id, username, role_id, is_banned, deleted_at, created_at,
              discord_id, discord_name, discord_linked_at,
              amp_username, amp_status, amp_note, amp_updated_at)
    ON <SITE_DB>.users TO '<BOT_USER>'@'<BOT_HOST>';
GRANT UPDATE (discord_id, discord_name, discord_linked_at, role_id,
              amp_username, amp_status, amp_note, amp_updated_at)
    ON <SITE_DB>.users TO '<BOT_USER>'@'<BOT_HOST>';

-- Raenge und ihre Rechte (nur lesen)
GRANT SELECT ON <SITE_DB>.roles            TO '<BOT_USER>'@'<BOT_HOST>';
GRANT SELECT ON <SITE_DB>.role_permissions TO '<BOT_USER>'@'<BOT_HOST>';

-- Verknuepfungs-Codes: pruefen und nach Gebrauch loeschen
GRANT SELECT, DELETE ON <SITE_DB>.discord_link_codes TO '<BOT_USER>'@'<BOT_HOST>';

-- Auftraege der Seite: lesen und als erledigt markieren
GRANT SELECT ON <SITE_DB>.bot_outbox TO '<BOT_USER>'@'<BOT_HOST>';
GRANT UPDATE (processed_at, attempts, last_error) ON <SITE_DB>.bot_outbox TO '<BOT_USER>'@'<BOT_HOST>';

-- News und Events lesen, Zusagen aus Discord eintragen
GRANT SELECT ON <SITE_DB>.news   TO '<BOT_USER>'@'<BOT_HOST>';
GRANT SELECT ON <SITE_DB>.events TO '<BOT_USER>'@'<BOT_HOST>';
GRANT SELECT, INSERT, UPDATE, DELETE ON <SITE_DB>.event_participants TO '<BOT_USER>'@'<BOT_HOST>';

-- Tickets: aus Discord eroeffnen und beantworten, Status nachziehen
GRANT SELECT, INSERT ON <SITE_DB>.tickets TO '<BOT_USER>'@'<BOT_HOST>';
GRANT UPDATE (status, assigned_to, updated_at, closed_at) ON <SITE_DB>.tickets TO '<BOT_USER>'@'<BOT_HOST>';
GRANT SELECT, INSERT ON <SITE_DB>.ticket_messages TO '<BOT_USER>'@'<BOT_HOST>';

-- Wiki (nur lesen, /wiki)
GRANT SELECT ON <SITE_DB>.wiki_pages TO '<BOT_USER>'@'<BOT_HOST>';

-- Pruefen:
SHOW GRANTS FOR '<BOT_USER>'@'<BOT_HOST>';
