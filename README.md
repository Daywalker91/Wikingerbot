# WikingerBot — Projektdokumentation
*Eigener Discord Bot für den Wikinger Server*

> Für die einmaligen Setup-Schritte (Discord-Bot anlegen, einladen, Rollen-Hierarchie) siehe [SETUP.md](SETUP.md).

---

## Projektziel

Ablösung von GatekeeperV2, Red Discord Bot und Sinusbot durch einen einheitlichen, selbst entwickelten Bot mit:
- Einheitlichem Berechtigungssystem
- Einheitlicher Datenbank
- Discord Slash-Commands als primäres Interface
- WebUI für detaillierte Konfiguration und Übersichten
- Cog-basierter Erweiterbarkeit

---

## Tech-Stack

| Komponente | Technologie | Begründung |
|---|---|---|
| Sprache | Python 3.11+ | Ausgereift, Red als Referenz, gute AMP-Unterstützung |
| Discord Library | discord.py | Größte Community, beste Dokumentation |
| REST API / Backend | FastAPI | Async-nativ, automatische API-Docs, sauber trennbar |
| WebUI Frontend | React | Modern, erweiterbar, bereits bekannt |
| Datenbank (Prod) | MariaDB | Läuft bereits in k3s |
| Datenbank (Dev) | SQLite | Einfach, kein Overhead lokal |
| ORM | SQLAlchemy (async) | Unterstützt MariaDB und SQLite, Datenbankwechsel einfach |
| AMP Integration | ampapi (Python) | Offizieller Wrapper für CubeCoders AMP REST API |
| Hosting | k3s oder AMP-Instanz | Beides möglich |

---

## Architektur-Übersicht

```
┌─────────────────────────────────────────────────────┐
│                   WikingerBot                       │
│                                                     │
│  ┌─────────────┐    ┌─────────────────────────┐    │
│  │  Discord    │    │       FastAPI            │    │
│  │  Bot Core   │    │       REST API           │    │
│  │ (discord.py)│    │                          │    │
│  └──────┬──────┘    └────────────┬────────────┘    │
│         │                        │                  │
│  ┌──────▼──────────────────────▼────────────┐      │
│  │              Cog Manager                  │      │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ │      │
│  │  │ AMP Cog  │ │ Mod Cog  │ │Music Cog │ │      │
│  │  └──────────┘ └──────────┘ └──────────┘ │      │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ │      │
│  │  │Whitelist │ │  Roles   │ │ Custom   │ │      │
│  │  │   Cog    │ │   Cog    │ │   Cog    │ │      │
│  │  └──────────┘ └──────────┘ └──────────┘ │      │
│  └──────────────────────┬───────────────────┘      │
│                         │                           │
│  ┌──────────────────────▼───────────────────┐      │
│  │           Datenbank Layer                 │      │
│  │     SQLAlchemy (async)                    │      │
│  │     MariaDB (Prod) / SQLite (Dev)         │      │
│  └───────────────────────────────────────────┘     │
│                                                     │
└─────────────────────────────────────────────────────┘
         │                          │
    ┌────▼────┐              ┌──────▼──────┐
    │Discord  │              │  React WebUI│
    │ API     │              │  Dashboard  │
    └─────────┘              └─────────────┘
         │
    ┌────▼────┐
    │  AMP    │
    │  REST   │
    │  API    │
    └─────────┘
```

---

## Ordnerstruktur

```
wikingerbot/
├── bot/                        # Discord Bot Core
│   ├── __init__.py
│   ├── main.py                 # Einstiegspunkt
│   ├── core/
│   │   ├── bot.py              # Bot-Klasse, Cog-Manager
│   │   ├── config.py           # Konfiguration (Env-Variablen)
│   │   └── permissions.py      # Berechtigungssystem
│   └── cogs/                   # Cog-Verzeichnis
│       ├── amp/                # AMP-Integration
│       │   ├── __init__.py
│       │   ├── cog.py
│       │   └── commands.py
│       ├── moderation/         # Moderation
│       │   ├── __init__.py
│       │   ├── cog.py
│       │   └── commands.py
│       ├── whitelist/          # Whitelist-System
│       │   ├── __init__.py
│       │   └── cog.py
│       ├── roles/              # Rollen-Management
│       │   ├── __init__.py
│       │   └── cog.py
│       └── music/              # Musik (später)
│           ├── __init__.py
│           └── cog.py
│
├── api/                        # FastAPI Backend
│   ├── __init__.py
│   ├── main.py                 # FastAPI App
│   ├── routers/
│   │   ├── servers.py          # AMP Server Endpoints
│   │   ├── moderation.py       # Mod-Log Endpoints
│   │   ├── whitelist.py        # Whitelist Endpoints
│   │   └── users.py            # User-Management
│   └── middleware/
│       └── auth.py             # API Authentifizierung
│
├── db/                         # Datenbank
│   ├── __init__.py
│   ├── base.py                 # SQLAlchemy Base
│   ├── session.py              # DB Session Management
│   └── models/
│       ├── user.py
│       ├── server.py
│       ├── modlog.py
│       ├── whitelist.py
│       └── config.py
│
├── web/                        # React Frontend
│   ├── public/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ServerStatus/
│   │   │   ├── ModLog/
│   │   │   ├── Whitelist/
│   │   │   └── UserManagement/
│   │   ├── pages/
│   │   │   ├── Dashboard.jsx
│   │   │   ├── Servers.jsx
│   │   │   ├── Moderation.jsx
│   │   │   └── Settings.jsx
│   │   └── App.jsx
│   └── package.json
│
├── docker/                     # Container-Konfiguration
│   ├── Dockerfile.bot
│   ├── Dockerfile.api
│   └── Dockerfile.web
├── k8s/                        # Kubernetes Manifeste
│   ├── deployment.yaml
│   ├── service.yaml
│   └── configmap.yaml
├── .env.example
├── docker-compose.yml          # Für lokale Entwicklung
└── requirements.txt
```

---

## Cog-Interface

Jedes Cog muss folgendes Interface implementieren:

```python
# bot/core/base_cog.py
from discord.ext import commands

class BaseCog(commands.Cog):
    """Basis-Klasse für alle WikingerBot Cogs"""

    # Pflichtattribute
    __cog_name__: str       # Eindeutiger Name
    __version__: str        # Semantic Versioning (z.B. "1.0.0")
    __description__: str    # Kurzbeschreibung
    __author__: str         # Autor

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.db        # DB-Session
        self.config = bot.config # Konfiguration

    async def cog_load(self):
        """Wird beim Laden des Cogs aufgerufen"""
        pass

    async def cog_unload(self):
        """Wird beim Entladen des Cogs aufgerufen"""
        pass

    async def cog_check(self, ctx):
        """Globale Permission-Check für alle Commands in diesem Cog"""
        return await self.bot.permissions.check(ctx)
```

**Cog laden/entladen per Discord-Command:**
```
/bot cog load name:moderation
/bot cog unload name:moderation
/bot cog reload name:moderation
/bot cog list
```

---

## Datenbankschema (Grundgerüst)

```sql
-- Benutzer
CREATE TABLE users (
    id          BIGINT PRIMARY KEY,      -- Discord User ID
    username    VARCHAR(100),
    steam_id    VARCHAR(50),
    created_at  DATETIME DEFAULT NOW(),
    updated_at  DATETIME DEFAULT NOW()
);

-- Rollen-Hierarchie
CREATE TABLE roles (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    guild_id    BIGINT,
    discord_role_id BIGINT,
    level       ENUM('owner','admin','mod','member'),
    created_at  DATETIME DEFAULT NOW()
);

-- Server (AMP-Instanzen)
CREATE TABLE servers (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    instance_name   VARCHAR(100) UNIQUE,
    display_name    VARCHAR(100),
    host            VARCHAR(255),
    console_channel BIGINT,
    chat_channel    BIGINT,
    event_channel   BIGINT,
    hidden          BOOLEAN DEFAULT FALSE,
    created_at      DATETIME DEFAULT NOW()
);

-- Moderation Log
CREATE TABLE modlog (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    guild_id    BIGINT,
    user_id     BIGINT,
    mod_id      BIGINT,
    action      ENUM('kick','ban','unban','warn','mute','unmute','timeout'),
    reason      TEXT,
    duration    INT,            -- Sekunden, NULL = permanent
    created_at  DATETIME DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Verwarnungen
CREATE TABLE warnings (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    guild_id    BIGINT,
    user_id     BIGINT,
    mod_id      BIGINT,
    reason      TEXT,
    points      INT DEFAULT 1,
    expired     BOOLEAN DEFAULT FALSE,
    created_at  DATETIME DEFAULT NOW()
);

-- Whitelist-Anfragen
CREATE TABLE whitelist_requests (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    user_id     BIGINT,
    server_id   INT,
    ign         VARCHAR(100),   -- In-Game Name
    status      ENUM('pending','approved','denied') DEFAULT 'pending',
    handled_by  BIGINT,
    created_at  DATETIME DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (server_id) REFERENCES servers(id)
);

-- Bot-Konfiguration
CREATE TABLE config (
    key         VARCHAR(100) PRIMARY KEY,
    value       TEXT,
    updated_at  DATETIME DEFAULT NOW()
);
```

---

## Berechtigungssystem

```
Owner   → Alles, kann Admins ernennen
Admin   → Alles außer Owner-Aktionen, kann Mods ernennen
Mod     → Moderation, Server steuern, Whitelist verwalten
Member  → Status sehen, Whitelist beantragen, Chat
```

Implementierung als Decorator:

```python
# Verwendung in Commands
@discord.app_commands.command()
@require_role("mod")        # Mindestens Mod
async def kick(self, interaction, user: discord.Member, reason: str):
    ...

@discord.app_commands.command()
@require_role("admin")      # Mindestens Admin
async def ban(self, interaction, user: discord.Member, reason: str):
    ...
```

---

## Geplante Cogs (v1)

| Cog | Ersetzt | Features |
|---|---|---|
| `amp` | GatekeeperV2 | Start/Stop/Status, Console, Chat-Bridge, Banner |
| `moderation` | Red (teilweise) | Kick/Ban/Warn/Timeout, ModLog |
| `whitelist` | GatekeeperV2 | Anfragen, Auto-Approve, Rollen-Vergabe |
| `roles` | Red (teilweise) | Autorole, Rollen-Management |
| `welcome` | Red (teilweise) | Willkommensnachrichten, Join-Events |

**Spätere Cogs (v2+):**

| Cog | Features |
|---|---|
| `music` | Musik-Wiedergabe (ersetzt Sinusbot) |
| `stats` | Server-Statistiken, Aktivitäts-Tracking |
| `trivia` | Quiz-System |
| `automod` | Automatische Moderation |

---

## WebUI Seiten

| Seite | Inhalt |
|---|---|
| Dashboard | Server-Übersicht, Online-Status, Spielerzahlen |
| Server | AMP-Instanzen verwalten, Start/Stop, Console-Log |
| Moderation | ModLog ansehen, Verwarnungen, gebannte User |
| Whitelist | Anfragen verwalten, genehmigen/ablehnen |
| Benutzer | User-Datenbank, Rollen, Steam-IDs |
| Einstellungen | Bot-Konfiguration, Cogs laden/entladen |

---

## Hosting

### Option A — k3s (empfohlen)
```yaml
# 3 Deployments:
# - wikingerbot-discord   (Bot Core)
# - wikingerbot-api       (FastAPI)
# - wikingerbot-web       (React via nginx)
# + MariaDB bereits vorhanden
```

### Option B — AMP-Instanz
```
# Generic Module in AMP
# Bot Core + FastAPI als ein Prozess
# SQLite statt MariaDB
```

---

## Entwicklungsplan

**Phase 1 — Grundgerüst**
- Bot Core + Cog-Manager
- Datenbankmodelle + Migrationen
- Berechtigungssystem
- FastAPI Grundstruktur

**Phase 2 — Kern-Cogs**
- AMP Cog (ersetzt GatekeeperV2)
- Moderation Cog
- Whitelist Cog

**Phase 3 — WebUI**
- React Dashboard
- Server-Übersicht
- ModLog + Whitelist Ansicht

**Phase 4 — Erweiterungen**
- Roles Cog
- Welcome Cog
- Weitere Cogs nach Bedarf

---

*WikingerBot | Daywalker91 | Stand: Juli 2026*
