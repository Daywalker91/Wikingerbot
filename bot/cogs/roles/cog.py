"""Autorole und Selbstwahl-Rollen.

- Autorole: Rollen, die jedes neue Mitglied automatisch bekommt (guild_config
  "autorole_ids"). Bei aktivem Regel-Screening von Discord erst, wenn das
  Mitglied die Regeln akzeptiert hat.
- Selbstwahl-Rollen: eine Bot-Nachricht mit Knoepfen, jeder Knopf schaltet
  eine Rolle an/aus. Die Rolle steckt in der custom_id des Knopfs
  (DynamicItem) - die Knoepfe funktionieren damit auch nach einem Neustart
  ohne eigene Tabelle; die Nachricht selbst ist der Speicher. Welche
  Nachrichten Panels sind, merkt sich der Bot in guild_config "role_panels"
  (fuer den Tab Rollen der Weboberflaeche).

Die Raenge/Berechtigungsrollen des Bots (guild_roles) und Rollen mit
Verwaltungsrechten lassen sich bewusst NICHT selbst waehlen.
"""

import json
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.core import punishment
from bot.core.whitelist_gate import gated_reason, gated_roles
from bot.core.base_cog import BaseCog
from bot.core.guild_config import get_config, set_config
from bot.core.permissions import Level, require_role
from db.models.role import GuildRole
from db.session import get_db_session

log = logging.getLogger(__name__)

CUSTOM_ID_PREFIX = "wb:role:"
MAX_BUTTONS = 25  # 5 Reihen a 5 Knoepfe - Discord-Grenze pro Nachricht

# Wer sich eine Rolle mit einem dieser Rechte selbst geben koennte, koennte den
# Server uebernehmen - solche Rollen gehen weder als Selbstwahl noch als Autorole.
DANGEROUS_PERMISSIONS = (
    "administrator",
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "manage_webhooks",
    "manage_messages",
    "manage_nicknames",
    "manage_expressions",
    "manage_events",
    "manage_threads",
    "ban_members",
    "kick_members",
    "moderate_members",
    "mention_everyone",
    "view_audit_log",
)

MESSAGE_LINK = re.compile(r"discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)")


def role_block_reason(role: discord.Role, bot_top_position: int, rank_role_ids: set[int] = frozenset()) -> str | None:
    """Grund, warum der Bot diese Rolle nicht vergeben darf - None = in Ordnung."""
    if role.is_default():
        return "@everyone kann man nicht vergeben."
    if role.managed:
        return f"{role.name} wird von Discord oder einer Integration verwaltet."
    if role.position >= bot_top_position:
        return f"{role.name} liegt über der Rolle des Bots – in den Servereinstellungen die Bot-Rolle darüber schieben."
    risky = [name for name in DANGEROUS_PERMISSIONS if getattr(role.permissions, name, False)]
    if risky:
        return f"{role.name} hat Verwaltungsrechte ({', '.join(risky)}) und ist dafür zu gefährlich."
    if role.id in rank_role_ids:
        return f"{role.name} ist eine Berechtigungsrolle des Bots (Mod/Admin/...) und wird nicht selbst gewählt."
    return None


def parse_message_ref(text: str) -> tuple[int | None, int] | None:
    """Nachrichten-Link -> (Kanal-ID, Nachrichten-ID); reine ID -> (None, ID)."""
    text = text.strip()
    match = MESSAGE_LINK.search(text)
    if match:
        return int(match.group(2)), int(match.group(3))
    if text.isdigit():
        return None, int(text)
    return None


def role_id_from_custom_id(custom_id: str | None) -> int | None:
    if custom_id and custom_id.startswith(CUSTOM_ID_PREFIX) and custom_id[len(CUSTOM_ID_PREFIX):].isdigit():
        return int(custom_id[len(CUSTOM_ID_PREFIX):])
    return None


async def rank_role_ids(guild_id: int) -> set[int]:
    """Berechtigungsrollen ab Mod - die darf man sich nicht selbst geben. Rollen der
    Stufe Member (z.B. die normale Mitgliederrolle als Autorole) sind harmlos."""
    async with get_db_session() as db:
        result = await db.execute(
            select(GuildRole.discord_role_id).where(GuildRole.guild_id == guild_id, GuildRole.level != Level.MEMBER)
        )
        return {row[0] for row in result.all()}


async def block_reason(role: discord.Role, guild: discord.Guild) -> str | None:
    """role_block_reason plus: Rollen von Servern mit Whitelist gibt es nur per Freigabe."""
    reason = role_block_reason(role, guild.me.top_role.position, await rank_role_ids(guild.id))
    if reason:
        return reason
    servers = (await gated_roles(guild.id)).get(role.id)
    return gated_reason(role.name, servers) if servers else None


async def get_autoroles(guild_id: int) -> list[int]:
    return [int(r) for r in json.loads(await get_config(guild_id, "autorole_ids", "[]") or "[]")]


async def set_autoroles(guild: discord.Guild, role_ids: list[int]) -> None:
    await set_config(guild.id, "autorole_ids", json.dumps(role_ids), guild.name)


PANELS_KEY = "role_panels"  # [{"channel_id": ..., "message_id": ...}, ...]


async def get_panels(guild_id: int) -> list[tuple[int, int]]:
    try:
        stored = json.loads(await get_config(guild_id, PANELS_KEY, "[]") or "[]")
    except json.JSONDecodeError:
        stored = []
    return [(int(p["channel_id"]), int(p["message_id"])) for p in stored if p.get("channel_id") and p.get("message_id")]


async def set_panels(guild: discord.Guild, panels: list[tuple[int, int]]) -> None:
    unique = list(dict.fromkeys(panels))
    await set_config(guild.id, PANELS_KEY, json.dumps([{"channel_id": str(c), "message_id": str(m)} for c, m in unique]), guild.name)


async def remember_panel(guild: discord.Guild, channel_id: int, message_id: int) -> None:
    panels = await get_panels(guild.id)
    if (channel_id, message_id) not in panels:
        await set_panels(guild, [*panels, (channel_id, message_id)])


async def forget_panel(guild: discord.Guild, message_id: int) -> None:
    await set_panels(guild, [p for p in await get_panels(guild.id) if p[1] != message_id])


def panel_embed(title: str, text: str) -> discord.Embed:
    return discord.Embed(title=title[:256], description=text[:4000], color=0x8B5A2B)


class RoleToggleButton(discord.ui.DynamicItem[discord.ui.Button], template=r"wb:role:(?P<role_id>\d+)"):
    """Knopf auf einem Rollen-Panel: schaltet genau eine Rolle an/aus."""

    def __init__(
        self,
        role_id: int,
        label: str | None = None,
        emoji: str | discord.PartialEmoji | None = None,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
    ) -> None:
        super().__init__(
            discord.ui.Button(custom_id=f"{CUSTOM_ID_PREFIX}{role_id}", label=label, emoji=emoji, style=style)
        )
        self.role_id = role_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str]):
        return cls(int(match["role_id"]), label=item.label, emoji=item.emoji, style=item.style)

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return
        role = guild.get_role(self.role_id)
        if role is None:
            await interaction.response.send_message("Diese Rolle gibt es nicht mehr.", ephemeral=True, delete_after=20)
            return
        # Bei jedem Klick neu pruefen - die Rolle koennte seit dem Anlegen des
        # Knopfs Verwaltungsrechte bekommen haben.
        reason = await block_reason(role, guild)
        if reason:
            await interaction.response.send_message(reason, ephemeral=True, delete_after=30)
            return
        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Selbstwahl-Rolle abgewaehlt")
                text = f"Rolle **{role.name}** entfernt."
            else:
                await member.add_roles(role, reason="Selbstwahl-Rolle gewaehlt")
                text = f"Rolle **{role.name}** vergeben."
        except discord.HTTPException as error:
            log.warning("Selbstwahl-Rolle %s fehlgeschlagen: %s", role.name, error)
            text = "Das hat nicht geklappt – dem Bot fehlt vermutlich das Recht „Rollen verwalten“."
        await interaction.response.send_message(text, ephemeral=True, delete_after=10)


def panel_buttons(message: discord.Message) -> list[RoleToggleButton]:
    """Liest die Rollen-Knoepfe einer Panel-Nachricht zurueck (die Nachricht ist der Speicher)."""
    buttons = []
    for row in message.components:
        for component in getattr(row, "children", []):
            role_id = role_id_from_custom_id(getattr(component, "custom_id", None))
            if role_id is not None:
                buttons.append(RoleToggleButton(role_id, component.label, component.emoji, component.style))
    return buttons


def build_view(buttons: list[RoleToggleButton]) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for button in buttons:
        view.add_item(button)
    return view


class RolesCog(BaseCog):
    """Autorole und Selbstwahl-Rollen per Knopf."""

    __cog_name__ = "roles"
    __version__ = "1.0.0"
    __description__ = "Autorole und Selbstwahl-Rollen"
    __author__ = "Daywalker91"

    roles_group = app_commands.Group(name="rollen", description="Autorole und Selbstwahl-Rollen")
    auto_group = app_commands.Group(name="auto", description="Rollen fuer neue Mitglieder", parent=roles_group)
    panel_group = app_commands.Group(name="panel", description="Nachrichten mit Rollen-Knoepfen", parent=roles_group)

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(RoleToggleButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(RoleToggleButton)

    # --- Autorole --------------------------------------------------------------

    async def _give_autoroles(self, member: discord.Member) -> None:
        # Mit Strafrolle gegangen und wiedergekommen: Strafrolle statt Autorole
        if await punishment.is_remembered(member.guild.id, member.id):
            role = await punishment.punish_role(member.guild)
            if role is not None and role_block_reason(role, member.guild.me.top_role.position) is None:
                try:
                    await member.add_roles(role, reason="Strafrolle beim Wiederbeitritt")
                except discord.HTTPException as error:
                    log.warning("Strafrolle fuer %s beim Wiederbeitritt fehlgeschlagen: %s", member, error)
                return
        role_ids = await get_autoroles(member.guild.id)
        roles = [r for r in (member.guild.get_role(i) for i in role_ids) if r is not None and r not in member.roles]
        gated = await gated_roles(member.guild.id)
        roles = [r for r in roles if role_block_reason(r, member.guild.me.top_role.position) is None and r.id not in gated]
        if not roles:
            return
        try:
            await member.add_roles(*roles, reason="Autorole")
        except discord.HTTPException as error:
            log.warning("Autorole fuer %s fehlgeschlagen: %s", member, error)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        # Mit Discords Regel-Screening erst nach dem Akzeptieren (on_member_update)
        if not member.bot and not member.pending:
            await self._give_autoroles(member)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.pending and not after.pending and not after.bot:
            await self._give_autoroles(after)

    @auto_group.command(name="hinzufuegen", description="Neue Mitglieder bekommen diese Rolle automatisch")
    @require_role(Level.ADMIN)
    async def auto_add(self, interaction: discord.Interaction, rolle: discord.Role) -> None:
        guild = interaction.guild
        reason = role_block_reason(rolle, guild.me.top_role.position)
        if not reason and (servers := (await gated_roles(guild.id)).get(rolle.id)):
            reason = gated_reason(rolle.name, servers)
        if reason:
            await interaction.response.send_message(reason, ephemeral=True, delete_after=20)
            return
        role_ids = await get_autoroles(guild.id)
        if rolle.id not in role_ids:
            role_ids.append(rolle.id)
            await set_autoroles(guild, role_ids)
        await interaction.response.send_message(
            f"Neue Mitglieder bekommen jetzt automatisch {rolle.mention}.", ephemeral=True, delete_after=20
        )

    @auto_group.command(name="entfernen", description="Rolle nicht mehr automatisch vergeben")
    @require_role(Level.ADMIN)
    async def auto_remove(self, interaction: discord.Interaction, rolle: discord.Role) -> None:
        role_ids = [i for i in await get_autoroles(interaction.guild_id) if i != rolle.id]
        await set_autoroles(interaction.guild, role_ids)
        await interaction.response.send_message(
            f"{rolle.mention} wird nicht mehr automatisch vergeben.", ephemeral=True, delete_after=20
        )

    @auto_group.command(name="liste", description="Zeigt die automatisch vergebenen Rollen")
    @require_role(Level.ADMIN)
    async def auto_list(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        lines = []
        for role_id in await get_autoroles(guild.id):
            role = guild.get_role(role_id)
            if role is None:
                lines.append(f"- gelöschte Rolle ({role_id})")
                continue
            problem = role_block_reason(role, guild.me.top_role.position)
            lines.append(f"- {role.mention}" + (f" ⚠️ {problem}" if problem else ""))
        text = "Automatisch vergeben:\n" + "\n".join(lines) if lines else "Es werden keine Rollen automatisch vergeben."
        await interaction.response.send_message(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    # --- Selbstwahl-Panels -----------------------------------------------------

    async def _resolve_panel(self, interaction: discord.Interaction, nachricht: str) -> discord.Message | None:
        ref = parse_message_ref(nachricht)
        if ref is None:
            await interaction.response.send_message(
                "Bitte den Nachrichten-Link (Rechtsklick → Link kopieren) oder die Nachrichten-ID angeben.",
                ephemeral=True,
                delete_after=20,
            )
            return None
        channel_id, message_id = ref
        channel = interaction.guild.get_channel(channel_id) if channel_id else interaction.channel
        try:
            message = await channel.fetch_message(message_id)
        except (discord.HTTPException, AttributeError):
            await interaction.response.send_message(
                "Nachricht nicht gefunden – bei einer reinen ID den Befehl im selben Kanal ausführen.",
                ephemeral=True,
                delete_after=20,
            )
            return None
        if message.author.id != self.bot.user.id:
            await interaction.response.send_message(
                "Das ist keine Nachricht des Bots – zuerst `/rollen panel erstellen`.", ephemeral=True, delete_after=20
            )
            return None
        return message

    @panel_group.command(name="erstellen", description="Postet eine Nachricht, an die Rollen-Knoepfe kommen")
    @app_commands.describe(kanal="Wohin", titel="Ueberschrift", text="Beschreibung, \\n fuer Zeilenumbruch")
    @require_role(Level.ADMIN)
    async def panel_create(
        self,
        interaction: discord.Interaction,
        kanal: discord.TextChannel,
        titel: str,
        text: str = "Klick auf einen Knopf, um dir die Rolle zu geben oder wieder zu nehmen.",
    ) -> None:
        embed = panel_embed(titel, text.replace("\\n", "\n"))
        try:
            message = await kanal.send(embed=embed)
        except discord.HTTPException as error:
            await interaction.response.send_message(f"Konnte nicht posten: {error.text}", ephemeral=True)
            return
        await remember_panel(interaction.guild, kanal.id, message.id)
        await interaction.response.send_message(
            f"Panel erstellt: {message.jump_url}\nJetzt Knöpfe hinzufügen mit `/rollen panel knopf` "
            "und diesem Link.",
            ephemeral=True,
        )

    @panel_group.command(name="knopf", description="Fuegt einem Panel einen Rollen-Knopf hinzu")
    @app_commands.describe(
        nachricht="Link oder ID der Panel-Nachricht",
        rolle="Rolle, die der Knopf an-/abschaltet",
        beschriftung="Text auf dem Knopf (sonst der Rollenname)",
        emoji="Optional ein Emoji, z.B. 🎮",
    )
    @require_role(Level.ADMIN)
    async def panel_button(
        self,
        interaction: discord.Interaction,
        nachricht: str,
        rolle: discord.Role,
        beschriftung: str | None = None,
        emoji: str | None = None,
    ) -> None:
        guild = interaction.guild
        reason = await block_reason(rolle, guild)
        if reason:
            await interaction.response.send_message(reason, ephemeral=True, delete_after=20)
            return
        message = await self._resolve_panel(interaction, nachricht)
        if message is None:
            return
        buttons = panel_buttons(message)
        if any(b.role_id == rolle.id for b in buttons):
            await interaction.response.send_message("Für diese Rolle gibt es schon einen Knopf.", ephemeral=True, delete_after=20)
            return
        if len(buttons) >= MAX_BUTTONS:
            await interaction.response.send_message(
                f"Mehr als {MAX_BUTTONS} Knöpfe passen nicht in eine Nachricht – ein zweites Panel erstellen.",
                ephemeral=True,
                delete_after=20,
            )
            return
        buttons.append(RoleToggleButton(rolle.id, (beschriftung or rolle.name)[:80], emoji.strip() if emoji else None))
        try:
            await message.edit(view=build_view(buttons))
        except discord.HTTPException as error:
            await interaction.response.send_message(
                f"Discord hat den Knopf abgelehnt (ungültiges Emoji?): {error.text}", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"Knopf für {rolle.mention} hinzugefügt.", ephemeral=True, delete_after=20,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @panel_group.command(name="entfernen", description="Entfernt einen Rollen-Knopf von einem Panel")
    @app_commands.describe(nachricht="Link oder ID der Panel-Nachricht", rolle="Rolle des Knopfs")
    @require_role(Level.ADMIN)
    async def panel_remove(self, interaction: discord.Interaction, nachricht: str, rolle: discord.Role) -> None:
        message = await self._resolve_panel(interaction, nachricht)
        if message is None:
            return
        buttons = [b for b in panel_buttons(message) if b.role_id != rolle.id]
        await message.edit(view=build_view(buttons) if buttons else None)
        await interaction.response.send_message(
            f"Knopf für {rolle.mention} entfernt.", ephemeral=True, delete_after=20,
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RolesCog(bot))
