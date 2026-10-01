"""Rangpruefung vor Moderationsaktionen (target_block_reason).

Discord laesst den Bot alles moderieren, was unter der BOT-Rolle steht - die
Rolle des ausfuehrenden Mods prueft Discord dabei nicht. Diese Tests sichern
ab, dass der Bot Discords eigene Regel nachbildet."""

from types import SimpleNamespace

from bot.cogs.moderation.cog import target_block_reason

OWNER_ID = 1
# top_role als Zahl: hoeher = maechtiger (wie discord.Role-Vergleiche nach Position)
MEMBER, MOD, BOT, ADMIN, OWNER_ROLE = 1, 2, 3, 4, 5


def member(id_, top_role):
    return SimpleNamespace(id=id_, top_role=top_role, mention=f"<@{id_}>")


BOT_MEMBER = member(99, BOT)


def test_mod_may_moderate_member():
    assert target_block_reason(member(10, MOD), member(20, MEMBER), BOT_MEMBER, OWNER_ID) is None


def test_mod_may_not_moderate_other_mod():
    # Die eigentliche Luecke: die Bot-Rolle steht ueber Mod, Discord haette es erlaubt
    reason = target_block_reason(member(10, MOD), member(11, MOD), BOT_MEMBER, OWNER_ID)
    assert reason is not None and "gleich hohe oder hoehere Rolle" in reason


def test_mod_may_not_moderate_higher_role():
    assert target_block_reason(member(10, MOD), member(30, ADMIN), BOT_MEMBER, OWNER_ID) is not None


def test_admin_blocked_when_target_above_bot():
    # Admin steht ueber Mod, aber der Bot kann keinen Admin anfassen
    reason = target_block_reason(member(30, ADMIN), member(31, ADMIN - 0.5), BOT_MEMBER, OWNER_ID)
    assert reason is not None and "Bot-Rolle" in reason


def test_nobody_may_moderate_server_owner():
    reason = target_block_reason(member(30, ADMIN), member(OWNER_ID, OWNER_ROLE), BOT_MEMBER, OWNER_ID)
    assert reason == "Der Server-Owner kann nicht moderiert werden."


def test_owner_may_moderate_regardless_of_own_top_role():
    # Der Owner darf alles - auch wenn seine hoechste Rolle niedrig waere
    owner = member(OWNER_ID, MEMBER)
    assert target_block_reason(owner, member(11, MOD), BOT_MEMBER, OWNER_ID) is None


def test_cannot_moderate_self():
    mod = member(10, MOD)
    assert target_block_reason(mod, mod, BOT_MEMBER, OWNER_ID) == "Du kannst dich nicht selbst moderieren."


def test_cannot_moderate_the_bot():
    assert target_block_reason(member(30, ADMIN), BOT_MEMBER, BOT_MEMBER, OWNER_ID) is not None


def test_bot_action_without_actor_only_checks_bot_rank():
    # Warn-Eskalation nach AutoMod: kein menschlicher Ausfuehrender
    assert target_block_reason(None, member(11, MOD), BOT_MEMBER, OWNER_ID) is None
    assert target_block_reason(None, member(30, ADMIN), BOT_MEMBER, OWNER_ID) is not None
