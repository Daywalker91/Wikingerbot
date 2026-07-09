from types import SimpleNamespace

from bot.cogs.banner.embed import build_embed, build_group_embed

_STATUS = SimpleNamespace(
    State=SimpleNamespace(name="Ready"),
    Uptime="1h 2m",
    Metrics={"Active Users": SimpleNamespace(RawValue=3, MaxValue=10)},
)


def test_build_embed_contains_core_fields():
    embed = build_embed("Valheim", "play.example.com", _STATUS, (3, 10))

    field_names = [field.name for field in embed.fields]
    assert "Status" in field_names
    assert "Spieler" in field_names
    assert embed.title == "Valheim"
    assert embed.timestamp is not None


def test_build_embed_does_not_duplicate_connect_address():
    # Die Adresse wird als eigener Text ueber der Nachricht gesendet (siehe
    # BannerCog._build_server_payload), nicht nochmal im Embed selbst.
    embed = build_embed("Valheim", "play.example.com", _STATUS, (3, 10))

    field_names = [field.name for field in embed.fields]
    assert "Verbinden" not in field_names


def test_build_embed_omits_players_field_when_none():
    embed = build_embed("Valheim", "play.example.com", _STATUS, None)

    field_names = [field.name for field in embed.fields]
    assert "Spieler" not in field_names


def test_build_embed_includes_whitelist_badge_field_when_count_given():
    embed = build_embed("Valheim", "play.example.com", _STATUS, (3, 10), whitelist_count=12, has_donator=True)

    whitelist_field = next(field for field in embed.fields if field.name == "Whitelist")
    assert "12" in whitelist_field.value
    assert "Donator" in whitelist_field.value


def test_build_embed_omits_whitelist_field_when_count_is_none():
    embed = build_embed("Valheim", "play.example.com", _STATUS, (3, 10))

    field_names = [field.name for field in embed.fields]
    assert "Whitelist" not in field_names


def test_build_group_embed_has_one_field_per_entry():
    entries = [
        ("Server A", "a.example.com", _STATUS, (3, 10), 5, False),
        ("Server B", "b.example.com", _STATUS, None, None, True),
    ]
    embed = build_group_embed("Alle Server", entries)

    assert embed.title == "Alle Server"
    assert len(embed.fields) == 2
    assert embed.fields[0].name == "Server A"
    assert embed.fields[1].name == "Server B"
