"""Tickets der Community-Seite in Discord - voll gespiegelt:

- Pro Ticket ein Thread im Staff-Kanal (Textkanal oder Forum). Die Startnachricht
  zeigt den Stand und hat die Knoepfe Uebernehmen / Schliessen / Wieder oeffnen.
- Alles aus dem Verlauf der Seite erscheint im Thread (interne Notizen mit 🔒,
  Statuswechsel als Systemzeile). Was der Support im Thread schreibt, landet als
  Antwort auf der Seite - "!intern ..." als interne Notiz.
- Das Mitglied bekommt Antworten des Supports und das Schliessen per DM, mit
  einem Knopf "Antworten", der direkt ins Ticket schreibt.
- /ticket eroeffnet ein Ticket (nur verknuepfte Mitglieder).
- Im Forum bekommt jeder Beitrag einen Status- und einen Kategorie-Tag. Fehlende
  Tags legt der Bot an (braucht "Kanaele verwalten" im Forum), sonst nutzt er nur
  die vorhandenen gleichnamigen.

Wer schreibt, muss verknuepft sein - jede Nachricht gehoert auf der Seite zu einem
Konto. Einstellungen im Tab "Tickets".
"""

import logging
import re
import time

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.tickets.site import (
    CATEGORIES,
    PRIORITIES,
    STATUSES,
    Ticket,
    TicketError,
    add_reply,
    change_status,
    create_ticket,
    fetch_ticket,
    is_staff,
    messages_after,
)
from bot.community import db as community_db
from bot.community import outbox
from bot.community.linking import user_for_discord
from bot.core.base_cog import BaseCog
from bot.core.entities import ensure_guild
from bot.core.guild_config import get_config
from db.models.community_post import CommunityPost
from db.session import get_db_session

log = logging.getLogger("wikingerbot.tickets")

THREAD_KIND = "ticket"  # channel_id = Elternkanal, message_id = Thread-ID (= ID der Startnachricht)
CURSOR_KIND = "ticket_cursor"  # message_id = zuletzt in den Thread gespiegelte Nachricht der Seite
DM_CURSOR_KIND = "ticket_dm"  # message_id = zuletzt fuer DMs gepruefte Nachricht (beim ersten Server gespeichert)
INTERNAL_PREFIX = "!intern"
COLOR = 0x5FA8A0
CREATE_LIMIT = 3  # Tickets pro 10 Minuten und Mitglied (wie auf der Seite)
MAX_FORUM_TAGS = 20  # Discord-Grenze pro Forum
MAX_THREAD_TAGS = 5  # Discord-Grenze pro Beitrag


def wanted_tags(ticket: Ticket) -> list[tuple[str, str | None]]:
    """(Name, Emoji) der Forum-Tags fuer ein Ticket: Status und Kategorie."""
    emoji, label = STATUSES.get(ticket.status, STATUSES["open"])
    return [(label, emoji), (CATEGORIES.get(ticket.category, ticket.category)[:20], None)]


def _our_tag_names() -> set[str]:
    return {label.casefold() for _, label in STATUSES.values()} | {c[:20].casefold() for c in CATEGORIES.values()}


def ticket_link(ticket_id: int) -> str | None:
    return community_db.site_link("tickets.view", id=ticket_id)


def thread_name(ticket: Ticket) -> str:
    return f"#{ticket.id} {ticket.subject}"[:100]


def status_embed(ticket: Ticket) -> discord.Embed:
    emoji, label = STATUSES.get(ticket.status, STATUSES["open"])
    embed = discord.Embed(title=f"🎫 #{ticket.id} {ticket.subject}"[:256], url=ticket_link(ticket.id), color=COLOR)
    embed.add_field(name="Status", value=f"{emoji} {label}")
    embed.add_field(name="Kategorie", value=CATEGORIES.get(ticket.category, ticket.category))
    embed.add_field(name="Priorität", value=PRIORITIES.get(ticket.priority, ticket.priority))
    member = ticket.author + (f" (<@{ticket.author_discord_id}>)" if ticket.author_discord_id else " (nicht verknüpft)")
    embed.add_field(name="Mitglied", value=member)
    embed.add_field(name="Zuständig", value=ticket.assigned_name or "–")
    embed.set_footer(text="Im Thread schreiben = Antwort auf der Seite · „!intern …“ = interne Notiz")
    return embed


class TicketActionButton(discord.ui.DynamicItem[discord.ui.Button], template=r"wb:ticket:(?P<ticket_id>\d+):(?P<action>claim|close|reopen)"):
    LABELS = {"claim": ("🙋", "Übernehmen", discord.ButtonStyle.primary), "close": ("✅", "Schließen", discord.ButtonStyle.secondary), "reopen": ("↩️", "Wieder öffnen", discord.ButtonStyle.secondary)}

    def __init__(self, ticket_id: int, action: str) -> None:
        emoji, label, style = self.LABELS[action]
        super().__init__(discord.ui.Button(custom_id=f"wb:ticket:{ticket_id}:{action}", emoji=emoji, label=label, style=style))
        self.ticket_id, self.action = ticket_id, action

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str]):
        return cls(int(match["ticket_id"]), match["action"])

    async def callback(self, interaction: discord.Interaction) -> None:
        cog: "TicketsCog | None" = interaction.client.get_cog("TicketsCog")
        if cog is None or not community_db.enabled():
            await interaction.response.send_message("Tickets sind gerade nicht verfügbar.", ephemeral=True)
            return
        site_user = await user_for_discord(interaction.user.id)
        if site_user is None:
            await interaction.response.send_message("Verknüpfe dich zuerst mit der Seite (/verknuepfen).", ephemeral=True)
            return
        try:
            await change_status(self.ticket_id, site_user.id, site_user.username, self.action)
        except TicketError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await interaction.response.defer()
        await cog.sync_ticket(self.ticket_id)


def thread_view(ticket: Ticket) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    if ticket.status == "closed":
        view.add_item(TicketActionButton(ticket.id, "reopen"))
    else:
        view.add_item(TicketActionButton(ticket.id, "claim"))
        view.add_item(TicketActionButton(ticket.id, "close"))
    return view


class ReplyModal(discord.ui.Modal, title="Antwort auf dein Ticket"):
    text = discord.ui.TextInput(label="Deine Antwort", style=discord.TextStyle.paragraph, min_length=2, max_length=4000)

    def __init__(self, ticket_id: int) -> None:
        super().__init__()
        self.ticket_id = ticket_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        site_user = await user_for_discord(interaction.user.id)
        if site_user is None:
            await interaction.response.send_message("Dein Discord-Konto ist nicht mehr verknüpft.", ephemeral=True)
            return
        try:
            await add_reply(self.ticket_id, site_user.id, str(self.text.value))
        except TicketError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        await interaction.response.send_message("Gesendet – steht jetzt im Ticket. Danke!", ephemeral=True)
        cog = interaction.client.get_cog("TicketsCog")
        if cog is not None:
            await cog.sync_ticket(self.ticket_id)  # spiegelt die Antwort in den Staff-Thread


class TicketReplyButton(discord.ui.DynamicItem[discord.ui.Button], template=r"wb:ticketreply:(?P<ticket_id>\d+)"):
    def __init__(self, ticket_id: int) -> None:
        super().__init__(discord.ui.Button(custom_id=f"wb:ticketreply:{ticket_id}", label="Antworten", emoji="✉️", style=discord.ButtonStyle.primary))
        self.ticket_id = ticket_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str]):
        return cls(int(match["ticket_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(ReplyModal(self.ticket_id))


class NewTicketModal(discord.ui.Modal, title="Neues Ticket"):
    subject = discord.ui.TextInput(label="Betreff", min_length=5, max_length=150)
    body = discord.ui.TextInput(label="Worum geht's?", style=discord.TextStyle.paragraph, min_length=10, max_length=4000)

    def __init__(self, cog: "TicketsCog", site_user_id: int, category: str) -> None:
        super().__init__()
        self.cog, self.site_user_id, self.category = cog, site_user_id, category

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            ticket_id = await create_ticket(self.site_user_id, str(self.subject.value), self.category, str(self.body.value))
        except TicketError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        self.cog.note_created(interaction.user.id)
        link = ticket_link(ticket_id)
        await interaction.response.send_message(
            f"Dein Ticket **#{ticket_id}** ist eingegangen – die Antwort kommt per DM." + (f" [Auf der Seite ansehen]({link})" if link else ""),
            ephemeral=True,
        )
        await self.cog.sync_ticket(ticket_id)


class TicketsCog(BaseCog):
    """Tickets der Seite <-> Staff-Threads und DMs."""

    __cog_name__ = "tickets"
    __version__ = "1.0.0"
    __description__ = "Tickets der Community-Seite in Discord"
    __author__ = "Daywalker91"

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self._from_discord: set[int] = set()  # im Thread geschrieben -> nicht nochmal hineinspiegeln
        self._created: dict[int, list[float]] = {}
        self._tags_denied: set[int] = set()  # Foren, in denen der Bot keine Tags anlegen darf

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(TicketActionButton, TicketReplyButton)
        for kind in ("ticket.created", "ticket.message", "ticket.updated"):
            outbox.register(kind, self._on_outbox)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(TicketActionButton, TicketReplyButton)
        for kind in ("ticket.created", "ticket.message", "ticket.updated"):
            outbox.unregister(kind, self._on_outbox)

    async def _on_outbox(self, payload: dict) -> None:
        await self.sync_ticket(int(payload["ticket_id"]))

    # --- Zuordnung Ticket <-> Thread ---------------------------------------------

    async def _get(self, kind: str, guild_id: int, ticket_id: int) -> CommunityPost | None:
        async with get_db_session() as db:
            return await db.get(CommunityPost, (kind, ticket_id, guild_id))

    async def _set(self, kind: str, guild: discord.Guild, ticket_id: int, channel_id: int, message_id: int) -> None:
        await ensure_guild(guild.id, guild.name)
        async with get_db_session() as db:
            row = await db.get(CommunityPost, (kind, ticket_id, guild.id))
            if row is None:
                db.add(CommunityPost(kind=kind, item_id=ticket_id, guild_id=guild.id, channel_id=channel_id, message_id=message_id))
            else:
                row.channel_id, row.message_id = channel_id, message_id
            await db.commit()

    async def _thread(self, guild: discord.Guild, ticket_id: int) -> discord.Thread | None:
        mapping = await self._get(THREAD_KIND, guild.id, ticket_id)
        if mapping is None:
            return None
        thread = guild.get_thread(mapping.message_id)
        if thread is None:
            try:
                thread = await guild.fetch_channel(mapping.message_id)
            except (discord.NotFound, discord.Forbidden):
                return None
        return thread if isinstance(thread, discord.Thread) else None

    async def _ticket_for_thread(self, thread: discord.Thread) -> int | None:
        from sqlalchemy import select

        async with get_db_session() as db:
            row = (
                await db.execute(
                    select(CommunityPost.item_id).where(
                        CommunityPost.kind == THREAD_KIND, CommunityPost.guild_id == thread.guild.id, CommunityPost.message_id == thread.id
                    )
                )
            ).first()
        return row[0] if row else None

    # --- Abgleich ------------------------------------------------------------------

    async def sync_ticket(self, ticket_id: int) -> list[str]:
        """Thread anlegen/aktualisieren, neue Nachrichten spiegeln, Mitglied per DM informieren."""
        ticket = await fetch_ticket(ticket_id)
        if ticket is None:
            return []
        done = []
        for guild in self.bot.guilds:
            channel_id = await get_config(guild.id, "tickets_channel_id")
            channel = guild.get_channel(int(channel_id)) if channel_id else None
            thread = await self._thread(guild, ticket_id)
            if thread is None:
                if channel is None:
                    continue
                thread = await self._create_thread(guild, channel, ticket)
                done.append(f"{guild.name}: Thread angelegt")
            else:
                await self._update_starter(thread, ticket)
            mirrored = await self._mirror(guild, thread, ticket)
            if mirrored:
                done.append(f"{guild.name}: {mirrored} Nachricht(en) gespiegelt")
            await self._update_thread(thread, ticket)
        # DMs unabhaengig von Threads (auch ohne Staff-Kanal, auch fuer Antworten aus dem Thread)
        await self._notify_new(ticket)
        return done

    async def _create_thread(self, guild: discord.Guild, channel, ticket: Ticket) -> discord.Thread:
        embed, view = status_embed(ticket), thread_view(ticket)
        role_id = await get_config(guild.id, "tickets_ping_role_id")
        role = guild.get_role(int(role_id)) if role_id else None
        mentions = discord.AllowedMentions(roles=[role] if role else False, users=False, everyone=False)
        if isinstance(channel, discord.ForumChannel):
            created = await channel.create_thread(
                name=thread_name(ticket),
                content=role.mention if role else None,
                embed=embed,
                view=view,
                allowed_mentions=mentions,
                applied_tags=await self._forum_tags(channel, ticket),
            )
            thread = created.thread
        else:
            starter = await channel.send(content=role.mention if role else None, embed=embed, view=view, allowed_mentions=mentions)
            thread = await starter.create_thread(name=thread_name(ticket), auto_archive_duration=10080)
        await self._set(THREAD_KIND, guild, ticket.id, channel.id, thread.id)
        return thread

    async def _forum_tags(self, forum: discord.ForumChannel, ticket: Ticket) -> list[discord.ForumTag]:
        """Status- und Kategorie-Tag des Tickets; fehlende werden im Forum angelegt, wenn erlaubt."""
        wanted = wanted_tags(ticket)
        by_name = {tag.name.casefold(): tag for tag in forum.available_tags}
        missing = [(name, emoji) for name, emoji in wanted if name.casefold() not in by_name]
        if missing and forum.id not in self._tags_denied:
            tags = list(forum.available_tags) + [discord.ForumTag(name=name, emoji=emoji) for name, emoji in missing]
            if len(tags) > MAX_FORUM_TAGS:
                log.warning("Forum #%s hat keinen Platz fuer weitere Tags (max. %s)", forum.name, MAX_FORUM_TAGS)
                self._tags_denied.add(forum.id)
            else:
                try:
                    forum = await forum.edit(available_tags=tags) or forum
                    by_name = {tag.name.casefold(): tag for tag in forum.available_tags}
                except discord.Forbidden:
                    log.warning("Tickets: keine Tags in #%s - dem Bot fehlt dort \"Kanaele verwalten\"", forum.name)
                    self._tags_denied.add(forum.id)
                except discord.HTTPException as error:
                    log.warning("Tickets: Tags in #%s nicht angelegt: %s", forum.name, error)
        return [by_name[name.casefold()] for name, _ in wanted if name.casefold() in by_name]

    async def _update_thread(self, thread: discord.Thread, ticket: Ticket) -> None:
        """Archiviert/oeffnet den Thread passend zum Status und zieht im Forum die Tags nach."""
        changes: dict = {}
        if isinstance(thread.parent, discord.ForumChannel):
            ours = _our_tag_names()
            # Tags, die das Team selbst gesetzt hat, bleiben stehen
            others = [tag for tag in thread.applied_tags if tag.name.casefold() not in ours]
            tags = (await self._forum_tags(thread.parent, ticket) + others)[:MAX_THREAD_TAGS]
            if {tag.id for tag in tags} != {tag.id for tag in thread.applied_tags}:
                changes["applied_tags"] = tags
        archived = ticket.status == "closed"
        if thread.archived != archived:
            changes["archived"] = archived
        if not changes:
            return
        # In einem Aufruf: ein archivierter Thread laesst sich sonst nicht mehr bearbeiten
        try:
            await thread.edit(**changes)
        except discord.HTTPException as error:
            if "applied_tags" not in changes:
                raise
            log.warning("Tags von Ticket #%s nicht gesetzt: %s", ticket.id, error)
            if "archived" in changes:
                await thread.edit(archived=archived)

    async def _starter(self, thread: discord.Thread) -> discord.Message | None:
        # Startnachricht hat dieselbe ID wie der Thread - im Forum liegt sie im Thread, sonst im Elternkanal
        for place in (thread, thread.parent):
            if place is None:
                continue
            try:
                return await place.fetch_message(thread.id)
            except (discord.NotFound, discord.Forbidden, AttributeError):
                continue
        return None

    async def _update_starter(self, thread: discord.Thread, ticket: Ticket) -> None:
        starter = await self._starter(thread)
        if starter is not None:
            try:
                await starter.edit(embed=status_embed(ticket), view=thread_view(ticket))
            except discord.HTTPException as error:
                log.info("Startnachricht von Ticket #%s nicht aktualisiert: %s", ticket.id, error)
        name = thread_name(ticket)
        if thread.name != name:
            try:
                await thread.edit(name=name)
            except discord.HTTPException:
                pass

    async def _mirror(self, guild: discord.Guild, thread: discord.Thread, ticket: Ticket) -> int:
        cursor = await self._get(CURSOR_KIND, guild.id, ticket.id)
        last = cursor.message_id if cursor else 0
        count = 0
        for message in await messages_after(ticket.id, last):
            last = message.id
            if message.id in self._from_discord:
                continue
            if message.user_id is None:
                text = f"ℹ️ *{message.body}*"
            elif message.internal:
                text = f"🔒 **{message.author or 'Gelöscht'}** (intern, Seite): {message.body}"
            else:
                text = f"**{message.author or 'Gelöscht'}** (Seite): {message.body}"
            for chunk in [text[i : i + 1900] for i in range(0, len(text), 1900)] or [""]:
                await thread.send(chunk, allowed_mentions=discord.AllowedMentions.none())
            count += 1
        if count or cursor is None or last != (cursor.message_id if cursor else 0):
            await self._set(CURSOR_KIND, guild, ticket.id, thread.id, last)
        return count

    async def _notify_new(self, ticket: Ticket) -> None:
        if not self.bot.guilds:
            return
        guild = self.bot.guilds[0]
        cursor = await self._get(DM_CURSOR_KIND, guild.id, ticket.id)
        messages = await messages_after(ticket.id, cursor.message_id if cursor else 0)
        if not messages:
            return
        # Ohne Merker (Ticket aelter als der Bot): nur die neueste Nachricht beachten,
        # sonst bekaeme das Mitglied den ganzen alten Verlauf auf einmal
        for message in messages if cursor else messages[-1:]:
            await self._notify_member(ticket, message)
        await self._set(DM_CURSOR_KIND, guild, ticket.id, 0, messages[-1].id)

    async def _notify_member(self, ticket: Ticket, message) -> None:
        """DM an das Mitglied: Antworten des Supports (keine internen) und das Schliessen."""
        if not ticket.author_discord_id or message.internal or message.user_id == ticket.user_id:
            return
        is_close = message.user_id is None and "geschlossen" in message.body
        if message.user_id is None and not is_close:
            return
        guild_ids = [g.id for g in self.bot.guilds]
        if guild_ids and await get_config(guild_ids[0], "tickets_dm", "true") != "true":
            return
        user = self.bot.get_user(ticket.author_discord_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(ticket.author_discord_id)
            except discord.HTTPException:
                return
        link = ticket_link(ticket.id)
        if is_close:
            embed = discord.Embed(title=f"✅ Ticket #{ticket.id} geschlossen", description=ticket.subject, url=link, color=COLOR)
            view = None
        else:
            embed = discord.Embed(
                title=f"✉️ Antwort auf Ticket #{ticket.id}", description=message.body[:3500], url=link, color=COLOR
            )
            embed.set_author(name=f"{message.author} (Support)")
            embed.set_footer(text=ticket.subject[:200])
            view = discord.ui.View(timeout=None)
            view.add_item(TicketReplyButton(ticket.id))
        try:
            await user.send(embed=embed, view=view)
        except discord.HTTPException:
            pass  # DMs zu

    # --- Nachrichten im Staff-Thread ---------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not isinstance(message.channel, discord.Thread) or not community_db.enabled():
            return
        ticket_id = await self._ticket_for_thread(message.channel)
        if ticket_id is None or not message.content:
            return
        site_user = await user_for_discord(message.author.id)
        if site_user is None:
            await message.reply("⚠️ Nicht übertragen – verknüpfe dich zuerst mit der Seite (/verknuepfen).", delete_after=20)
            return
        internal = message.content.lower().startswith(INTERNAL_PREFIX)
        body = message.content[len(INTERNAL_PREFIX):].strip() if internal else message.content
        try:
            message_id = await add_reply(ticket_id, site_user.id, body, internal=internal)
        except TicketError as error:
            await message.reply(f"⚠️ Nicht übertragen: {error}", delete_after=20)
            return
        self._from_discord.add(message_id)
        try:
            await message.add_reaction("🔒" if internal else "✅")
        except discord.HTTPException:
            pass
        await self.sync_ticket(ticket_id)

    # --- /ticket ---------------------------------------------------------------------

    def note_created(self, discord_id: int) -> None:
        self._created.setdefault(discord_id, []).append(time.monotonic())

    def _too_many(self, discord_id: int) -> bool:
        now = time.monotonic()
        recent = [t for t in self._created.get(discord_id, []) if now - t < 600]
        self._created[discord_id] = recent
        return len(recent) >= CREATE_LIMIT

    @app_commands.command(name="ticket", description="Eroeffnet ein Ticket beim Support")
    @app_commands.choices(kategorie=[app_commands.Choice(name=label, value=key) for key, label in CATEGORIES.items()])
    async def ticket(self, interaction: discord.Interaction, kategorie: app_commands.Choice[str]) -> None:
        if not community_db.enabled():
            await interaction.response.send_message("Die Community-Seite ist nicht angebunden.", ephemeral=True)
            return
        site_user = await user_for_discord(interaction.user.id)
        if site_user is None:
            await interaction.response.send_message(
                "Tickets gehören auf der Seite zu einem Konto – verknüpfe dich zuerst (/verknuepfen).", ephemeral=True
            )
            return
        if self._too_many(interaction.user.id) and not await is_staff(site_user.id):
            await interaction.response.send_message("Du hast gerade schon mehrere Tickets erstellt. Bitte warte ein paar Minuten.", ephemeral=True)
            return
        await interaction.response.send_modal(NewTicketModal(self, site_user.id, kategorie.value))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketsCog(bot))
