"""welcome-Cog: Platzhalter und Ein/Aus-Logik."""

from bot.cogs.welcome.cog import DEFAULT_WELCOME, is_off, render


def test_render_placeholders_and_newlines():
    text = render(
        "Hallo {user} ({name})\\nWillkommen auf {server}, Nr. {count}",
        mention="<@1>",
        name="Ragnar",
        server="Wikinger",
        count=42,
    )
    assert text == "Hallo <@1> (Ragnar)\nWillkommen auf Wikinger, Nr. 42"


def test_render_keeps_unknown_placeholders():
    assert render("{user} {unbekannt}", mention="<@1>", name="x", server="y", count=1) == "<@1> {unbekannt}"


def test_render_default_text():
    text = render(DEFAULT_WELCOME, mention="<@1>", name="Ragnar", server="Wikinger", count=7)
    assert "<@1>" in text and "Wikinger" in text and "7" in text


def test_render_is_capped_at_discord_limit():
    assert len(render("x" * 3000, mention="", name="", server="", count=0)) == 2000


def test_is_off():
    for value in (None, "", "aus", "AUS", " off ", "-"):
        assert is_off(value)
    assert not is_off("Hallo {user}")
