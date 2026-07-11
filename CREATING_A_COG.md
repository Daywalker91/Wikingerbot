# WikingerBot — Ein neues Cog erstellen

Ein Cog ist eine in sich geschlossene, portable Erweiterung: Discord-
Commands, optional eine FastAPI-Route und optional eine React-Seite liegen
zusammen in **einem** Ordner unter `bot/cogs/<name>/`. Nichts davon muss
irgendwo zentral eingetragen werden — alles wird automatisch gefunden.

---

## 1. Discord-Cog-Grundgerüst

Minimal-Skelett:

```
bot/cogs/<name>/
├── __init__.py    # leer
└── cog.py
```

`cog.py`:

```python
import discord
from discord import app_commands
from discord.ext import commands

from bot.core.base_cog import BaseCog


class PingCog(BaseCog):
    __cog_name__ = "ping"
    __version__ = "1.0.0"
    __description__ = "Beispiel-Cog"
    __author__ = "Dein Name"

    @app_commands.command(name="ping", description="Antwortet mit Pong")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Pong!", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PingCog(bot))
```

`bot/core/bot.py`s `discover_cogs()` findet jedes Verzeichnis unter
`bot/cogs/` mit einer `cog.py` automatisch und lädt es beim Bot-Start
(`load_cog()`) — kein manuelles Registrieren nötig.

### Der wichtige Stolperstein: `app_commands.Group`

Braucht dein Cog Unterbefehle (`/server status`, `/server start`, ...),
**muss** die `Group` ein **Klassenattribut** sein, niemals Modul-Level:

```python
class PingCog(BaseCog):
    ping_group = app_commands.Group(name="ping", description="...")   # ✅ Klassenattribut

    @ping_group.command(name="echo")
    async def echo(self, interaction, text: str) -> None:
        ...
```

Grund: discord.py bindet `self` an Unterbefehle nur, wenn es das
`Group`/`Command`-Objekt in der **Klassen-Namespace** findet
(`Cog._inject`). Bei einer Modul-Level-Group bleibt `self` ungebunden — der
Fehler zeigt sich als `CommandSignatureMismatch`, obwohl die eigentliche
Ursache ein simpler `TypeError` ist. Zusätzlich: Attributnamen dürfen nicht
mit `bot_`/`cog_` beginnen (von discord.pys `CogMeta` reserviert).

### Etablierte Muster (mit Beispiel-Cog)

| Muster | Wofür | Beispiel |
|---|---|---|
| `require_role(Level)` (`bot/core/permissions.py`) | Decorator, Mindest-Berechtigung für einen Command | `bot/cogs/amp/cog.py` |
| `check_level_interaction()` (`bot/core/permissions.py`) | Dasselbe für `discord.ui.View`-Button-Callbacks (kein `app_commands.Command`) | `bot/cogs/whitelist/cog.py` (`WhitelistReviewView`) |
| `send_temp_followup()` (`bot/core/discord_utils.py`) | Ephemere Antwort, die sich nach ~20s selbst löscht | überall |
| `get_db_session()` (`db/session.py`) | Async-Context-Manager für DB-Zugriff aus einem Cog | überall |
| Lokale, pro Cog duplizierte Autocomplete-Helfer | z.B. `_autocomplete_instance_name` | `bot/cogs/amp/cog.py`, `bot/cogs/whitelist/cog.py`, `bot/cogs/banner/cog.py` — bewusst dupliziert statt cross-cog importiert |

### Mehrere Dateien pro Cog

Lohnt sich, sobald ein Cog reines Rendering/Hilfslogik hat, die nicht
Discord-spezifisch ist — siehe `bot/cogs/banner/` mit `image.py` (Pillow-
Rendering), `embed.py` (Embed-Bau) und `themes.py` (Konstanten), alle nur
von `cog.py` importiert, nicht von anderen Cogs.

---

## 2. Optionale WebUI-Anbindung

Ein Cog **kann** zusätzlich eine FastAPI-Route und/oder eine React-Seite
mitbringen — beides ist unabhängig voneinander optional. Ein Cog ohne
WebUI-Bezug (z.B. `moderation` aktuell) braucht weder `api.py` noch `web/`.

```
bot/cogs/<name>/
├── cog.py
├── api.py              # optional: FastAPI-Router
└── web/                 # optional: React-Seite
    └── <Name>Page.tsx
```

### `api.py` — FastAPI-Router

Muss ein Modul-Level-Objekt `router: APIRouter` exportieren:

```python
from fastapi import APIRouter, Depends

from api.middleware.auth import CurrentUser, get_current_user
from db.session import get_db

router = APIRouter(prefix="/ping", tags=["ping"])


@router.get("")
async def ping(user: CurrentUser = Depends(get_current_user)) -> dict:
    return {"pong": True}
```

`api/cog_routers.py`s `discover_cog_routers()` sammelt jede `bot/cogs/*/
api.py` automatisch ein und `api/main.py` registriert sie — auch hier kein
manuelles Eintragen nötig, einfach die Datei anlegen. Zugriff auf
`CurrentUser`/`get_current_user`/`require_level(Level)` (aus
`api.middleware.auth`) und `get_db` (aus `db.session`, FastAPI-Dependency-
Variante von `get_db_session()`) wie in jedem anderen Router auch.

Referenz-Beispiel: `bot/cogs/amp/api.py` (`/servers`-Route fürs Dashboard).

### `web/<Name>Page.tsx` — React-Seite

Muss `export const route = { path, navLabel }` und einen `default export`
(die Komponente) bereitstellen:

```tsx
export const route = { path: "/ping", navLabel: "Ping" };

export default function PingPage() {
  return <h1>Pong!</h1>;
}
```

`web/src/App.tsx`s `import.meta.glob("../../bot/cogs/*/web/*Page.tsx", {
eager: true })` findet jede solche Datei automatisch und baut daraus die
Routen-Tabelle — auch hier keine Änderung an `App.tsx` selbst nötig.

Cog-eigener API-Client (z.B. `web/api.ts` neben `<Name>Page.tsx`) importiert
den gemeinsamen `fetch`-Wrapper via `import { apiFetch } from "@/api/client"`
(Alias auf `web/src/`, siehe `web/vite.config.ts`):

```ts
import { apiFetch } from "@/api/client";

export async function getPing(): Promise<{ pong: boolean }> {
  return apiFetch("/ping");
}
```

Referenz-Beispiel: `bot/cogs/amp/web/` (`DashboardPage.tsx`, `api.ts`,
`ServerCard.tsx`, `types.ts`).

**Wichtig für die Modul-Auflösung**: `node_modules` liegt bewusst im
Repo-Root (nicht in `web/`), da Node/TypeScript `node_modules` nur über
Eltern-Verzeichnisse findet — `bot/cogs/<name>/web/` ist kein Nachfahre von
`web/`, aber beide sind Nachfahren des Repo-Roots. `npm install`/`npm run
dev`/`npm run build` daher immer vom **Repo-Root** aus ausführen, nicht aus
`web/` heraus.

### Was zentral bleibt (kein Cog-Bezug)

Login-Seite, Auth-Guard, allgemeines Seitenlayout/Navigation
(`web/src/pages/Login.tsx`, `web/src/auth/*`) sowie der `/auth/*`-Router
selbst (`api/routers/auth.py`) gehören keinem einzelnen Cog — dafür gibt
es keinen fachlichen Eigentümer, das bleibt zentral in `web/src/` bzw.
`api/routers/`.
