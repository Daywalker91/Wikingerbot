from types import SimpleNamespace

from PIL import Image

from bot.cogs.banner.image import (
    GROUP_HEADER_HEIGHT,
    HEIGHT,
    PANEL_HEIGHT,
    WIDTH,
    extract_players,
    render_banner,
    render_banner_group,
)

_STATUS = SimpleNamespace(
    State=SimpleNamespace(name="Ready"),
    Uptime="1h 2m",
    Metrics={"Active Users": SimpleNamespace(RawValue=3, MaxValue=10)},
)
_STATUS_NO_METRICS = SimpleNamespace(State=SimpleNamespace(name="Stopped"), Uptime="", Metrics={})


def _open(buffer) -> Image.Image:
    buffer.seek(0)
    return Image.open(buffer)


def test_extract_players_returns_tuple_when_metric_present():
    assert extract_players(_STATUS) == (3, 10)


def test_extract_players_returns_none_when_metric_missing():
    assert extract_players(_STATUS_NO_METRICS) is None


def test_render_banner_produces_valid_png_with_expected_dimensions():
    buffer = render_banner("Valheim", "play.example.com", _STATUS, (3, 10))
    image = _open(buffer)

    assert image.format == "PNG"
    assert image.size == (WIDTH, HEIGHT)


def test_render_banner_background_priority_image_over_colors_over_theme():
    theme_only = _open(render_banner("Server", "host", _STATUS, None, theme="forest"))
    custom_colors = _open(
        render_banner("Server", "host", _STATUS, None, theme="forest", color_start="#ff0000", color_end="#0000ff")
    )

    # Oben in der Mitte (unbedeckt von Text-Streifen und abgerundeten Ecken)
    # unterscheidet sich je nach Prioritaet.
    sample_point = (WIDTH // 2, 5)
    assert theme_only.convert("RGB").getpixel(sample_point) != custom_colors.convert("RGB").getpixel(sample_point)


def test_render_banner_blur_changes_pixels_versus_unblurred():
    sharp = _open(render_banner("Server", "host", _STATUS, None, color_start="#ff0000", color_end="#0000ff", blur=0))
    blurred = _open(
        render_banner("Server", "host", _STATUS, None, color_start="#ff0000", color_end="#0000ff", blur=10)
    )

    assert list(sharp.convert("RGB").getdata()) != list(blurred.convert("RGB").getdata())


def test_render_banner_with_whitelist_badge_does_not_crash():
    buffer = render_banner(
        "Server", "host", _STATUS, (3, 10), whitelist_count=12, has_donator=True
    )
    image = _open(buffer)
    assert image.size == (WIDTH, HEIGHT)


def test_render_banner_text_color_changes_title_pixels():
    white_text = _open(
        render_banner("Valheim", "host", _STATUS, None, color_start="#000000", color_end="#000000")
    )
    red_text = _open(
        render_banner(
            "Valheim", "host", _STATUS, None, color_start="#000000", color_end="#000000", text_color="#ff0000"
        )
    )

    # Auf reinschwarzem Hintergrund muss sich der (weisse vs. rote) Text irgendwo
    # sichtbar unterscheiden - exakte Glyphen-Koordinaten sind fontabhaengig, daher
    # ueber alle Pixel vergleichen statt einen einzelnen Punkt zu erraten.
    assert list(white_text.convert("RGB").getdata()) != list(red_text.convert("RGB").getdata())


def test_render_banner_group_produces_stacked_image():
    entries = [
        ("Server A", "a.example.com", _STATUS, (3, 10), 5, False),
        ("Server B", "b.example.com", _STATUS_NO_METRICS, None, None, True),
    ]
    buffer = render_banner_group(entries)
    image = _open(buffer)

    assert image.format == "PNG"
    assert image.width == WIDTH
    assert image.height == GROUP_HEADER_HEIGHT + PANEL_HEIGHT * len(entries)
