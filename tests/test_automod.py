"""automod-Cog: Regeln ohne Discord."""

from collections import deque

from bot.cogs.automod.rules import (
    DEFAULT_CONFIG,
    MessageHistory,
    caps_ratio,
    check_message,
    count_emojis,
    domain_allowed,
    extract_domains,
    merged_config,
)


def config(**changes):
    c = merged_config({})
    for key, value in changes.items():
        if isinstance(value, dict):
            c[key].update(value)
        else:
            c[key] = value
    return c


def single(text, at=0.0):
    return deque([(at, " ".join(text.lower().split()))])


def test_merged_config_keeps_defaults_and_does_not_share_state():
    c = merged_config({"enabled": True, "flood": {"messages": 3}})
    assert c["enabled"] and c["flood"] == {"on": True, "messages": 3, "seconds": 8}
    c["links"]["allow"].append("x.org")
    assert DEFAULT_CONFIG["links"]["allow"] == []


def test_normal_message_passes():
    assert check_message(config(), "Hallo zusammen, wer ist heute Abend auf dem Server?", single("x"), 0) is None


def test_flood():
    history = MessageHistory()
    reason = None
    for i in range(8):
        recent = history.add((1, 1), f"nachricht {i}", at=i * 0.5)
        reason = check_message(config(), f"nachricht {i}", recent, i * 0.5) or reason
    assert reason and "Zu viele Nachrichten" in reason


def test_no_flood_when_spread_out():
    history = MessageHistory()
    for i in range(10):
        recent = history.add((1, 1), f"nachricht {i}", at=i * 5)
        assert check_message(config(), f"nachricht {i}", recent, i * 5) is None


def test_duplicates():
    history = MessageHistory()
    results = []
    for i in range(3):
        recent = history.add((1, 1), "Kauft   Gold!", at=i * 10)
        results.append(check_message(config(), "kauft gold!", recent, i * 10))
    assert results[:2] == [None, None] and "wiederholt" in results[2]


def test_caps():
    assert caps_ratio("HALLO hallo") == 0.5
    assert "Großbuchstaben" in check_message(config(), "WARUM GEHT DAS NICHT", single("x"), 0)
    assert check_message(config(), "OK DANKE", single("x"), 0) is None  # zu kurz


def test_emojis():
    text = "🔥" * 6 + "<:wikinger:123>" * 5
    assert count_emojis(text) == 11
    assert "Emojis" in check_message(config(), text, single(text), 0)


def test_links():
    text = "schau https://www.YouTube.com/watch?v=1 und discord.gg/abc"
    assert extract_domains(text) == ["youtube.com", "discord.gg"]
    assert domain_allowed("music.youtube.com", ["youtube.com"])
    assert not domain_allowed("evil-youtube.com", ["youtube.com"])

    allow = config(links={"mode": "allowlist", "allow": ["youtube.com"]})
    assert "discord.gg" in check_message(allow, text, single(text), 0)
    assert check_message(allow, "https://youtube.com/x", single("x"), 0) is None
    assert "nicht erlaubt" in check_message(config(links={"mode": "block"}), "https://a.org", single("x"), 0)
    assert check_message(config(), text, single(text), 0) is None  # Standard: Links aus
