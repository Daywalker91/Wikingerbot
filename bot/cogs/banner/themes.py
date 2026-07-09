"""Eingebaute Verlaufs-Themes und Presets fuer die Banner-Editor-UI.

Keine externen Bild-Assets - Hintergruende sind entweder ein generierter
Zweifarben-Verlauf oder ein vom Nutzer bereitgestelltes Bild (Upload oder
Steam-Artwork), siehe bot/cogs/banner/image.py.
"""

BANNER_THEMES: dict[str, tuple[str, str]] = {
    "midnight": ("#0f2027", "#2c5364"),
    "forest": ("#134e5e", "#71b280"),
    "sunset": ("#ff512f", "#dd2476"),
    "ocean": ("#2b5876", "#4e4376"),
}
DEFAULT_THEME = "midnight"

# Discord kennt keinen Colorpicker in Slash-Commands - der Editor bietet
# stattdessen eine kuratierte Auswahl an Preset-Farben zur Wahl an.
PRESET_COLORS: dict[str, str] = {
    "Weiss": "#ffffff",
    "Schwarz": "#000000",
    "Mitternachtsblau": "#0f2027",
    "Waldgruen": "#134e5e",
    "Sonnenuntergang-Rot": "#ff512f",
    "Ozeanblau": "#2b5876",
    "Violett": "#5f2c82",
    "Anthrazit": "#232526",
    "Weinrot": "#6d0000",
    "Petrol": "#0f4c5c",
    "Gold": "#b8860b",
    "Rosa": "#c94b4b",
}

BLUR_LEVELS: dict[str, int] = {
    "Kein": 0,
    "Leicht": 2,
    "Mittel": 5,
    "Stark": 10,
}
