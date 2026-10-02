"""Texte der Community-Seite fuer Discord aufbereiten (gemeinsam fuer news, events, ...)."""

import re


def plain_excerpt(text: str, length: int = 350) -> str:
    """Wie excerpt() der Seite: [[Seite|Text]] -> Text, Formatierungszeichen weg."""
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text or "")
    text = re.sub(r"[*`~>#]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= length else text[: length - 1].rstrip() + "…"
