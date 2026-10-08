"""Radiosender: Name -> Adresse ("music_stations") und Name -> Kategorie
("music_station_categories"), beide als JSON in der Server-Konfiguration.
Reine Funktionen, damit testbar; Slash-Commands und Oberflaeche nutzen dieselben."""

from urllib.parse import urlsplit, urlunsplit

STATIONS_KEY = "music_stations"
CATEGORIES_KEY = "music_station_categories"
NO_CATEGORY = "Ohne Kategorie"
MAX_NAME = 100
MAX_CATEGORY = 40


def normalize_url(url: str) -> str:
    """Zum Vergleich: ohne Leerzeichen, Schema/Host klein, ohne abschliessenden Schraegstrich."""
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, ""))


def clean_category(text: str | None) -> str:
    """Leerzeichen zusammenfassen, Laenge begrenzen; "" = ohne Kategorie.
    Mehrere Gruppen ("Rock;Pop") -> die erste."""
    first = (text or "").split(";", 1)[0]
    cleaned = " ".join(first.split())[:MAX_CATEGORY]
    return "" if cleaned.casefold() == NO_CATEGORY.casefold() else cleaned


def category_of(categories: dict, name: str) -> str:
    return categories.get(name, "") or ""


def used_categories(stations: dict, categories: dict) -> list[str]:
    """Alle vergebenen Kategorien, alphabetisch (ohne "Ohne Kategorie")."""
    return sorted({category_of(categories, n) for n in stations} - {""}, key=str.casefold)


def find_category(categories: dict, wanted: str) -> str:
    """Schreibweise einer vorhandenen Kategorie uebernehmen ("rock" -> "Rock")."""
    wanted = clean_category(wanted)
    for existing in set(categories.values()):
        if existing.casefold() == wanted.casefold():
            return existing
    return wanted


def search_stations(stations: dict, categories: dict, query: str = "", category: str | None = None) -> list[str]:
    """Sendernamen, alphabetisch. query: alle Woerter muessen in Name oder Kategorie
    vorkommen. category: nur diese Kategorie ("" bzw. NO_CATEGORY = ohne Kategorie)."""
    words = query.casefold().split()
    if category is not None:
        category = "" if category == NO_CATEGORY else category.casefold()
    result = []
    for name in stations:
        own = category_of(categories, name)
        if category is not None and own.casefold() != category:
            continue
        haystack = f"{name} {own}".casefold()
        if all(word in haystack for word in words):
            result.append(name)
    return sorted(result, key=str.casefold)


def label(name: str, category: str) -> str:
    """Anzeige in der Discord-Auswahl: "Name · Kategorie" (hoechstens 100 Zeichen)."""
    if not category:
        return name[:MAX_NAME]
    suffix = f" · {category}"
    return name[: MAX_NAME - len(suffix)] + suffix


def station_conflict(stations: dict, name: str, url: str) -> str | None:
    """Warum dieser Sender nicht neu eingetragen wird - oder None. Schutz vor Doppelten."""
    wanted = normalize_url(url)
    for existing, existing_url in stations.items():
        if normalize_url(existing_url) == wanted:
            return f"Diese Adresse ist schon als **{existing}** eingetragen."
    if name.strip().casefold() in {n.casefold() for n in stations}:
        return f"Einen Sender **{name.strip()}** gibt es schon – anderen Namen wählen oder den alten erst entfernen."
    return None


def import_stations(stations: dict, entries, categories: dict | None = None, category: str = "") -> tuple[int, int]:
    """Eintraege einer Sender-Liste (Titel, Adresse[, Gruppe]) in `stations` uebernehmen.
    Gleiche Adresse = schon da; gleicher Name mit anderer Adresse bekommt " (2)" usw.
    Kategorie: `category`, sonst die Gruppe aus der Liste (group-title)."""
    urls = {normalize_url(u) for u in stations.values()}
    forced = clean_category(category)
    added = known = 0
    for entry in entries:
        title, url = entry[0], entry[1]
        group = entry[2] if len(entry) > 2 else ""
        if normalize_url(url) in urls:
            known += 1
            continue
        name, n = title[:MAX_NAME] or "Sender", 2
        while name in stations:
            name, n = f"{title[:94]} ({n})", n + 1
        stations[name] = url
        urls.add(normalize_url(url))
        chosen = forced or (find_category(categories, group) if categories is not None else "")
        if categories is not None and chosen:
            categories[name] = chosen
        added += 1
    return added, known


def remove_stations(stations: dict, categories: dict, names) -> int:
    removed = 0
    for name in names:
        if stations.pop(name, None) is not None:
            removed += 1
        categories.pop(name, None)
    return removed


def set_category(stations: dict, categories: dict, names, category: str) -> int:
    """Kategorie fuer diese Sender setzen ("" = entfernen). Anzahl geaenderter Sender."""
    chosen = find_category(categories, category)
    changed = 0
    for name in names:
        if name not in stations:
            continue
        if chosen:
            categories[name] = chosen
        else:
            categories.pop(name, None)
        changed += 1
    return changed


def prune_categories(stations: dict, categories: dict) -> dict:
    """Kategorien von Sendern, die es nicht mehr gibt, weglassen."""
    return {n: c for n, c in categories.items() if n in stations and c}


def list_pages(names: list[str], categories: dict, per_page: int = 40, max_chars: int = 3800) -> list[str]:
    """Senderliste nach Kategorien gruppiert, in Seiten fuer ein Embed (Kategorie-Ueberschrift
    wird auf der naechsten Seite wiederholt). "Ohne Kategorie" kommt zuletzt."""
    groups: dict[str, list[str]] = {}
    for name in names:
        groups.setdefault(category_of(categories, name), []).append(name)
    order = sorted((c for c in groups if c), key=str.casefold) + ([""] if "" in groups else [])
    pages, lines, count = [], [], 0

    def flush() -> None:
        nonlocal lines, count
        if lines:
            pages.append("\n".join(lines))
        lines, count = [], 0

    for category in order:
        title = category or NO_CATEGORY
        if count >= per_page - 1:  # keine Ueberschrift allein am Seitenende
            flush()
        lines.append(f"**{title}** ({len(groups[category])})")
        for name in groups[category]:
            line = f"- {name}"
            if count >= per_page or sum(len(x) + 1 for x in lines) + len(line) > max_chars:
                flush()
                lines.append(f"**{title}** (weiter)")
            lines.append(line)
            count += 1
    flush()
    return pages
