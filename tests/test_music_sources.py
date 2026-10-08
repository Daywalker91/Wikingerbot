"""Musik-Quellen: Abrufe nie ins interne Netz (auch nicht ueber Weiterleitungen)."""


async def test_redirect_into_internal_network_is_blocked(monkeypatch):
    """Eine oeffentliche Adresse, die ins Heimnetz weiterleitet: jedes Ziel wird geprueft."""
    import httpx
    import pytest

    from bot.cogs.music import sources

    async def check(url):
        if "10.0.0." in url:
            raise sources.SourceError("Adressen im internen Netz sind nicht erlaubt.")

    def handler(request):
        if request.url.host == "radio.example":
            return httpx.Response(302, headers={"location": "http://10.0.0.5/admin.m3u"})
        return httpx.Response(200, content=b"http://10.0.0.5/stream")

    real = httpx.AsyncClient
    monkeypatch.setattr(sources, "check_public_url", check)
    monkeypatch.setattr(sources.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(sources.SourceError, match="internen Netz"):
        await sources.resolve_stream_url("https://radio.example/live.m3u")


def test_parse_playlist_entries_m3u_and_pls():
    from bot.cogs.music.sources import parse_playlist_entries

    m3u = "#EXTM3U\n#EXTINF:-1 tvg-logo=\"x\",Radio Bob\nhttps://stream.example/bob.mp3\n\n#EXTINF:-1,Rock Antenne\nhttps://rock.example/live\nhttps://stream.example/bob.mp3\nhttps://files.example/Mein_Lied.mp3\n"
    assert [entry[:2] for entry in parse_playlist_entries(m3u)] == [
        ("Radio Bob", "https://stream.example/bob.mp3"),
        ("Rock Antenne", "https://rock.example/live"),
        ("Mein Lied", "https://files.example/Mein_Lied.mp3"),
    ]
    pls = "[playlist]\nFile1=https://a.example/1\nTitle1=Eins\nFile2=https://b.example/2\nNumberOfEntries=2\n"
    assert [entry[:2] for entry in parse_playlist_entries(pls)] == [("Eins", "https://a.example/1"), ("2", "https://b.example/2")]


def test_station_duplicates_are_refused():
    from bot.cogs.music.cog import import_stations, station_conflict

    stations = {"Radio Bob": "https://stream.example/bob.mp3"}
    assert "schon als" in station_conflict(stations, "Bob 2", "HTTPS://Stream.example/bob.mp3/")
    assert "gibt es schon" in station_conflict(stations, "radio bob", "https://andere.example/x")
    assert station_conflict(stations, "Neu", "https://neu.example/live") is None

    added, known = import_stations(stations, [("Radio Bob", "https://stream.example/bob.mp3"), ("Radio Bob", "https://other.example/bob"), ("Jazz", "https://jazz.example")])
    assert (added, known) == (2, 1)
    assert stations["Radio Bob (2)"] == "https://other.example/bob" and "Jazz" in stations


def test_github_links_and_clean_titles():
    from bot.cogs.music.sources import github_raw_url, parse_playlist_entries

    page = "https://github.com/user/repo/blob/main/Radio%20Stations.m3u"
    assert github_raw_url(page) == "https://raw.githubusercontent.com/user/repo/main/Radio%20Stations.m3u"
    assert github_raw_url("https://example.com/list.m3u") == "https://example.com/list.m3u"
    assert parse_playlist_entries("#EXTINF:0, - RP MELLOW\nhttp://s.example/m") == [("RP MELLOW", "http://s.example/m", "")]


def test_playlist_groups_become_categories():
    from bot.cogs.music.sources import parse_playlist_entries
    from bot.cogs.music.stations import import_stations

    m3u = (
        '#EXTM3U\n#EXTINF:-1 tvg-name="A, B" group-title="Rock;Pop",Radio Bob\nhttps://bob.example/1\n'
        "#EXTGRP:Jazz\n#EXTINF:-1,Jazz One\nhttps://jazz.example/1\nhttps://plain.example/x\n"
    )
    entries = parse_playlist_entries(m3u)
    assert entries == [
        ("Radio Bob", "https://bob.example/1", "Rock;Pop"),
        ("Jazz One", "https://jazz.example/1", "Jazz"),
        ("x", "https://plain.example/x", ""),
    ]
    stations, categories = {}, {"Alt": "rock"}
    assert import_stations(stations, entries, categories) == (3, 0)
    assert categories == {"Alt": "rock", "Radio Bob": "rock", "Jazz One": "Jazz"}  # vorhandene Schreibweise, erste Gruppe

    stations, categories = {}, {}
    import_stations(stations, entries, categories, category="Import")
    assert set(categories.values()) == {"Import"}


def test_station_search_and_pages():
    from bot.cogs.music.stations import NO_CATEGORY, label, list_pages, search_stations, used_categories

    stations = {"Rock Antenne": "a", "Bob": "b", "Jazz FM": "c", "Klassik Radio": "d"}
    categories = {"Rock Antenne": "Rock", "Bob": "Rock", "Jazz FM": "Jazz"}
    assert search_stations(stations, categories, "rock") == ["Bob", "Rock Antenne"]  # Kategorie zaehlt mit
    assert search_stations(stations, categories, "rock ant") == ["Rock Antenne"]
    assert search_stations(stations, categories, "", "rock") == ["Bob", "Rock Antenne"]
    assert search_stations(stations, categories, "", NO_CATEGORY) == ["Klassik Radio"]
    assert used_categories(stations, categories) == ["Jazz", "Rock"]
    assert label("x" * 120, "Rock") == "x" * 93 + " · Rock" and len(label("x" * 120, "Rock")) == 100

    many = {f"Sender {i:03}": str(i) for i in range(95)}
    pages = list_pages(sorted(many), {n: "Pop" for n in list(many)[:50]}, per_page=40)
    assert len(pages) == 3
    assert pages[0].startswith("**Pop** (50)") and pages[1].startswith("**Pop** (weiter)")
    assert sum(p.count("\n- ") + p.startswith("- ") for p in pages) == 95
    assert all(not p.rstrip().endswith(")") or "\n- " in p for p in pages)  # keine Ueberschrift allein am Ende


def test_better_names_rename_and_tidy():
    from bot.cogs.music.sources import title_from_url
    from bot.cogs.music.stations import rename_station, tidy_names

    assert title_from_url("https://hls.somafm.com/hls/groovesalad/320k/program.m3u8") == "somafm groovesalad 320k"
    assert title_from_url(
        "http://as-hls-ww-live.akamaized.net/pool_1/live/ww/bbc_6music/bbc_6music.isml/bbc_6music-audio%3d320000.norewind.m3u8"
    ) == "bbc 6music"
    assert title_from_url("https://files.example/Mein_Lied.mp3") == "Mein Lied"

    stations = {
        "program": "https://hls.somafm.com/hls/groovesalad/320k/program.m3u8",
        "program (2)": "https://hls.somafm.com/hls/groovesalad/FLAC/program.m3u8",
        "bbc 6music-audio%3d320000.norewind": "http://a.akamaized.net/x/bbc_6music/bbc_6music.isml/bbc_6music-audio%3d320000.norewind.m3u8",
        "Mein Lieblingssender": "https://hls.somafm.com/hls/dronezone/320k/program.m3u8",  # selbst benannt
    }
    categories = {"program (2)": "Chill"}
    renamed = tidy_names(stations, categories)
    assert sorted(new for _, new in renamed) == ["bbc 6music", "somafm groovesalad 320k", "somafm groovesalad FLAC"]
    assert "Mein Lieblingssender" in stations and categories == {"somafm groovesalad FLAC": "Chill"}
    assert tidy_names(stations, categories) == []  # zweites Mal: nichts mehr zu tun

    assert rename_station(stations, categories, "somafm groovesalad FLAC", "Groove Salad FLAC") is None
    assert categories == {"Groove Salad FLAC": "Chill"}
    assert "gibt es schon" in rename_station(stations, categories, "bbc 6music", "groove salad flac")
    assert rename_station(stations, categories, "gibtsnicht", "x") == "Diesen Sender gibt es nicht."
