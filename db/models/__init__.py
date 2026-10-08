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
from db.models.web_session import RememberToken, WebSession
from db.models.stats import StatsDaily, StatsMemberDaily
from db.models.community_post import CommunityPost
from db.models.amp_account import AmpAccount
from db.models.panel_request import PanelRoleRequest
from db.models.server_notice import ServerNotice

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
    "RememberToken",
    "StatsDaily",
    "StatsMemberDaily",
    "CommunityPost",
    "AmpAccount",
    "PanelRoleRequest",
    "ServerNotice",
]
