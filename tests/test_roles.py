"""roles-Cog: Sicherheitspruefung der Rollen, Nachrichten-Bezug, Panel-Knoepfe."""

from types import SimpleNamespace

import discord

from bot.cogs.roles.cog import (
    RoleToggleButton,
    build_view,
    get_autoroles,
    panel_buttons,
    parse_message_ref,
    role_block_reason,
    role_id_from_custom_id,
)
from bot.core.guild_config import set_config
from db.models.guild import Guild


def fake_role(role_id=10, name="Ark", position=5, managed=False, default=False, **perms):
    return SimpleNamespace(
        id=role_id,
        name=name,
        position=position,
        managed=managed,
        is_default=lambda: default,
        permissions=discord.Permissions(**perms),
    )


def test_plain_role_is_ok():
    assert role_block_reason(fake_role(), bot_top_position=10) is None


def test_blocked_roles():
    assert "everyone" in role_block_reason(fake_role(default=True), 10)
    assert "verwaltet" in role_block_reason(fake_role(managed=True), 10)
    assert "über der Rolle des Bots" in role_block_reason(fake_role(position=10), 10)
    assert "administrator" in role_block_reason(fake_role(administrator=True), 10)
    assert "ban_members" in role_block_reason(fake_role(ban_members=True), 10)
    assert "Berechtigungsrolle" in role_block_reason(fake_role(role_id=7), 10, rank_role_ids={7})


def test_harmless_permissions_are_fine():
    role = fake_role(send_messages=True, connect=True, speak=True, attach_files=True)
    assert role_block_reason(role, 10) is None


def test_parse_message_ref():
    assert parse_message_ref("https://discord.com/channels/1/22/333") == (22, 333)
    assert parse_message_ref("https://ptb.discordapp.com/channels/1/22/333") == (22, 333)
    assert parse_message_ref(" 4444 ") == (None, 4444)
    assert parse_message_ref("quatsch") is None


def test_role_id_from_custom_id():
    assert role_id_from_custom_id("wb:role:123") == 123
    assert role_id_from_custom_id("wb:role:abc") is None
    assert role_id_from_custom_id("anderes:123") is None
    assert role_id_from_custom_id(None) is None


async def test_panel_roundtrip_keeps_existing_buttons():
    """Knoepfe einer Panel-Nachricht werden aus den Komponenten zurueckgelesen -
    fremde Komponenten (andere custom_id) werden ignoriert."""
    view = build_view([RoleToggleButton(1, "Ark", "🦖"), RoleToggleButton(2, "Valheim")])
    view.add_item(discord.ui.Button(custom_id="fremd:1", label="x"))
    message = SimpleNamespace(components=[discord.components.ActionRow(row) for row in _rows(view)])

    buttons = panel_buttons(message)
    assert [(b.role_id, b.item.label) for b in buttons] == [(1, "Ark"), (2, "Valheim")]
    assert str(buttons[0].item.emoji) == "🦖"


def _rows(view):
    """View -> rohe Komponenten-Dicts wie von der Discord-API."""
    return view.to_components()


async def test_autoroles_stored_per_guild(db_session):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    assert await get_autoroles(1) == []
    await set_config(1, "autorole_ids", "[5, 6]")
    assert await get_autoroles(1) == [5, 6]
