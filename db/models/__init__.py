"""Importiert alle Modelle, damit Alembic-Autogenerate sie ueber Base.metadata sieht."""

from db.models.guild import Guild
from db.models.user import User
from db.models.role import GuildRole, Level
from db.models.server import BannerType, ConsoleFilterMode, Server
from db.models.banner_group import BannerGroup, BannerGroupLayout
from db.models.console_pattern import ConsolePattern, ConsolePatternKind, ConsolePatternOverride
from db.models.modlog import ModLogEntry, Warning
from db.models.whitelist import WhitelistRequest
from db.models.config import GuildConfig
from db.models.bot_setting import BotSetting
from db.models.web_session import WebSession

__all__ = [
    "Guild",
    "User",
    "GuildRole",
    "Level",
    "Server",
    "BannerType",
    "BannerGroup",
    "BannerGroupLayout",
    "ConsoleFilterMode",
    "ConsolePattern",
    "ConsolePatternKind",
    "ConsolePatternOverride",
    "ModLogEntry",
    "Warning",
    "WhitelistRequest",
    "GuildConfig",
    "BotSetting",
    "WebSession",
]
