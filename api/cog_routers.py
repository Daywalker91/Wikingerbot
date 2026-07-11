"""Sammelt FastAPI-Router aus bot/cogs/*/api.py ein.

Eigenstaendige Entsprechung zu bot/core/bot.py's discover_cogs() fuer
Discord-Cogs (gleiches Scan-Prinzip: jedes Verzeichnis unter bot/cogs/ mit
der jeweiligen Konventionsdatei wird automatisch eingebunden) - aber
technisch getrennt implementiert, da die API ein anderer Prozess ist und
kein discord.py-Extension-Mechanismus zur Verfuegung steht.

Ein Cog ohne api.py (z.B. weil er keine WebUI-Seite hat) wird einfach
uebersprungen, genau wie discover_cogs() Cogs ohne cog.py uebergeht.
"""

import importlib
from pathlib import Path

from fastapi import APIRouter

COGS_PATH = Path(__file__).resolve().parent.parent / "bot" / "cogs"


def discover_cog_routers() -> list[APIRouter]:
    routers: list[APIRouter] = []
    if not COGS_PATH.exists():
        return routers
    for path in sorted(COGS_PATH.iterdir()):
        if not path.is_dir() or path.name.startswith("_"):
            continue
        if not (path / "api.py").exists():
            continue
        module = importlib.import_module(f"bot.cogs.{path.name}.api")
        router = getattr(module, "router", None)
        if router is not None:
            routers.append(router)
    return routers
