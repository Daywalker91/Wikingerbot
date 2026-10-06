"""Pillow-Rendering fuer die Bild-Variante des Server-Banners.

Kennt weder Discord-Interactions noch DB-Sessions - reine Bild-Erzeugung aus
einfachen Werten, damit es unabhaengig testbar bleibt.
"""

import io

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from bot.cogs.banner.themes import BANNER_THEMES, DEFAULT_THEME

WIDTH = 800
HEIGHT = 300
PANEL_HEIGHT = 100
GROUP_HEADER_HEIGHT = 20
CORNER_RADIUS = 20

STATE_COLOR_READY = (46, 204, 113)
STATE_COLOR_DOWN = (231, 76, 60)
STATE_COLOR_TRANSITION = (149, 165, 166)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _gradient(width: int, height: int, color_start: str, color_end: str) -> Image.Image:
    start = _hex_to_rgb(color_start)
    end = _hex_to_rgb(color_end)
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = tuple(round(start[i] + (end[i] - start[i]) * ratio) for i in range(3))
        draw.line([(0, y), (width, y)], fill=color)
    return image


def _background(
    width: int,
    height: int,
    *,
    background_path: str | None = None,
    color_start: str | None = None,
    color_end: str | None = None,
    theme: str | None = None,
) -> Image.Image:
    """Hintergrund-Prioritaet: eigenes Bild > eigene Verlaufsfarben > benanntes Theme > Standard-Theme."""
    if background_path:
        with Image.open(background_path) as source:
            source = source.convert("RGB")
            return _center_crop(source, width, height)
    if color_start and color_end:
        return _gradient(width, height, color_start, color_end)
    theme_key = theme if theme in BANNER_THEMES else DEFAULT_THEME
    theme_start, theme_end = BANNER_THEMES[theme_key]
    return _gradient(width, height, theme_start, theme_end)


def _center_crop(image: Image.Image, width: int, height: int) -> Image.Image:
    src_ratio = image.width / image.height
    dst_ratio = width / height
    if src_ratio > dst_ratio:
        new_width = round(image.height * dst_ratio)
        left = (image.width - new_width) // 2
        image = image.crop((left, 0, left + new_width, image.height))
    else:
        new_height = round(image.width / dst_ratio)
        top = (image.height - new_height) // 2
        image = image.crop((0, top, image.width, top + new_height))
    return image.resize((width, height), Image.LANCZOS)


def _rounded(image: Image.Image, radius: int = CORNER_RADIUS) -> Image.Image:
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, image.width - 1, image.height - 1], radius=radius, fill=255)
    rounded = Image.new("RGBA", image.size)
    rounded.paste(image, (0, 0), mask)
    return rounded


def extract_players(status) -> tuple[int, int] | None:
    """Extrahiert (aktuell, maximal) aus AMPs StatusResponse.Metrics, falls verfuegbar."""
    metric = status.Metrics.get("Active Users") if status.Metrics else None
    if metric is None:
        return None
    return metric.RawValue, metric.MaxValue


def _status_color(state_name: str) -> tuple[int, int, int]:
    if state_name == "Ready":
        return STATE_COLOR_READY
    if state_name in ("Stopped", "Failed", "Suspended"):
        return STATE_COLOR_DOWN
    return STATE_COLOR_TRANSITION


def _draw_star(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, fill) -> None:
    import math

    points = []
    for i in range(10):
        angle = math.pi / 2 + i * math.pi / 5
        radius = size if i % 2 == 0 else size * 0.45
        points.append((cx + radius * math.cos(angle), cy - radius * math.sin(angle)))
    draw.polygon(points, fill=fill)


def _draw_lock(draw: ImageDraw.ImageDraw, x: float, y: float, size: float, fill) -> None:
    body = [x, y + size * 0.4, x + size, y + size]
    draw.rounded_rectangle(body, radius=size * 0.15, fill=fill)
    shackle_box = [x + size * 0.2, y - size * 0.1, x + size * 0.8, y + size * 0.55]
    draw.arc(shackle_box, start=180, end=360, fill=fill, width=max(2, round(size * 0.12)))


def _shadow_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int] = (255, 255, 255, 255),
) -> None:
    """Zeichnet Text mit einem kleinen Schlagschatten statt einem deckenden Balken -
    damit das Hintergrundbild ueberall sichtbar bleibt."""
    x, y = xy
    draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, 170))
    draw.text((x, y), text, font=font, fill=fill)


def _badge_backdrop(draw: ImageDraw.ImageDraw, left: float, top: float, right: float, bottom: float) -> None:
    """Schmaler, abgerundeter Schatten-Kasten nur hinter den Badges - kein Balken uebers ganze Bild."""
    draw.rounded_rectangle([left - 8, top - 6, right + 8, bottom + 6], radius=10, fill=(0, 0, 0, 130))


def _draw_badges(
    draw: ImageDraw.ImageDraw,
    font: ImageFont.ImageFont,
    right: float,
    bottom: float,
    *,
    whitelist_count: int | None,
    has_donator: bool,
) -> None:
    if whitelist_count is None and not has_donator:
        return

    cursor_x = right
    if has_donator:
        cursor_x -= 24
    if whitelist_count is not None:
        text_width = draw.textlength(str(whitelist_count), font=font)
        cursor_x -= text_width + 22

    _badge_backdrop(draw, cursor_x - 6, bottom - 24, right, bottom)

    cursor_x = right
    if has_donator:
        cursor_x -= 24
        _draw_star(draw, cursor_x, bottom - 12, 11, fill=(241, 196, 15, 255))
        cursor_x -= 10
    if whitelist_count is not None:
        text = str(whitelist_count)
        text_width = draw.textlength(text, font=font)
        cursor_x -= text_width
        draw.text((cursor_x, bottom - 22), text, font=font, fill=(255, 255, 255, 255))
        cursor_x -= 22
        _draw_lock(draw, cursor_x, bottom - 22, 16, fill=(255, 255, 255, 255))


def _draw_panel(
    image: Image.Image,
    *,
    top: int,
    height: int,
    display_name: str,
    status,
    players: tuple[int, int] | None,
    whitelist_count: int | None,
    has_donator: bool,
    font_title: ImageFont.ImageFont,
    font_body: ImageFont.ImageFont,
    text_color: tuple[int, int, int, int] = (255, 255, 255, 255),
) -> None:
    """Zeichnet Titel/Status/Uptime-Zeile ueber das volle Panel verteilt, mit Schlagschatten
    statt einem deckenden Balken - das Hintergrundbild bleibt dadurch ueberall sichtbar.
    Die Verbinden-Adresse wird bewusst NICHT ins Bild gemalt (siehe unten)."""
    draw = ImageDraw.Draw(image, "RGBA")
    padding = 16
    state_name = status.State.name
    color = _status_color(state_name)

    _shadow_text(draw, (padding, top + 8), display_name, font_title, fill=text_color)

    dot_y = top + 8 + font_title.size + 12
    draw.ellipse([padding, dot_y, padding + 14, dot_y + 14], fill=color + (255,))
    draw.ellipse([padding + 1, dot_y + 1, padding + 13, dot_y + 13], outline=(0, 0, 0, 120))
    status_text = state_name
    if players is not None:
        status_text += f"   Spieler: {players[0]}/{players[1]}"
    _shadow_text(draw, (padding + 20, dot_y - 3), status_text, font_body, fill=text_color)

    # Die Verbinden-Adresse steht bereits als eigener, kopierbarer Text ueber der
    # Nachricht (siehe BannerCog._build_server_payload) - hier nicht nochmal duplizieren.
    if hasattr(status, "Uptime") and status.Uptime:
        _shadow_text(draw, (padding, top + height - 24), f"Uptime: {status.Uptime}", font_body, fill=text_color)

    _draw_badges(
        draw,
        font_body,
        image.width - padding,
        top + height - 22,
        whitelist_count=whitelist_count,
        has_donator=has_donator,
    )


def render_banner(
    display_name: str,
    host: str,
    status,
    players: tuple[int, int] | None,
    *,
    theme: str | None = None,
    background_path: str | None = None,
    color_start: str | None = None,
    color_end: str | None = None,
    text_color: str | None = None,
    blur: int = 0,
    whitelist_count: int | None = None,
    has_donator: bool = False,
) -> io.BytesIO:
    background = _background(
        WIDTH, HEIGHT, background_path=background_path, color_start=color_start, color_end=color_end, theme=theme
    )
    if blur:
        background = background.filter(ImageFilter.GaussianBlur(radius=blur))
    image = background.convert("RGBA")

    font_title = ImageFont.load_default(size=28)
    font_body = ImageFont.load_default(size=18)

    _draw_panel(
        image,
        top=HEIGHT - 110,
        height=110,
        display_name=display_name,
        status=status,
        players=players,
        whitelist_count=whitelist_count,
        has_donator=has_donator,
        font_title=font_title,
        font_body=font_body,
        text_color=_hex_to_rgb(text_color) + (255,) if text_color else (255, 255, 255, 255),
    )

    rounded = _rounded(image)
    buffer = io.BytesIO()
    rounded.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def render_banner_group(
    entries: list[tuple[str, str, object, tuple[int, int] | None, int | None, bool]],
    *,
    background_path: str | None = None,
    color_start: str | None = None,
    color_end: str | None = None,
    text_color: str | None = None,
    theme: str | None = None,
    blur: int = 0,
) -> io.BytesIO:
    height = GROUP_HEADER_HEIGHT + PANEL_HEIGHT * len(entries)
    background = _background(
        WIDTH, height, background_path=background_path, color_start=color_start, color_end=color_end, theme=theme
    )
    if blur:
        background = background.filter(ImageFilter.GaussianBlur(radius=blur))
    image = background.convert("RGBA")

    font_title = ImageFont.load_default(size=20)
    font_body = ImageFont.load_default(size=14)
    resolved_text_color = _hex_to_rgb(text_color) + (255,) if text_color else (255, 255, 255, 255)

    for index, (display_name, _host, status, players, whitelist_count, has_donator) in enumerate(entries):
        _draw_panel(
            image,
            top=GROUP_HEADER_HEIGHT + PANEL_HEIGHT * index,
            height=PANEL_HEIGHT,
            display_name=display_name,
            status=status,
            players=players,
            whitelist_count=whitelist_count,
            has_donator=has_donator,
            font_title=font_title,
            font_body=font_body,
            text_color=resolved_text_color,
        )

    rounded = _rounded(image)
    buffer = io.BytesIO()
    rounded.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
