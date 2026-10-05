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


def test_build_embed_shows_connect_address_once_on_top():
    # Adresse kopierbar oben in der Karte (Beschreibung), nicht nochmal als Feld
    embed = build_embed("Valheim", "play.example.com", _STATUS, (3, 10))

    assert embed.description == "Verbinden: `play.example.com`"
    assert "Verbinden" not in [field.name for field in embed.fields]
    assert build_embed("Valheim", "", _STATUS, None).description is None


def test_image_card_keeps_address_and_image_together():
    from bot.cogs.banner.embed import image_card

    card = image_card("play.example.com:2456", "banner_7.png", (40, 200, 80))
    assert card.description == "Verbinden: `play.example.com:2456`"
    assert card.image.url == "attachment://banner_7.png"
    assert card.colour.to_rgb() == (40, 200, 80)


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
