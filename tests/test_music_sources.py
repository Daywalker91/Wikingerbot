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
    assert parse_playlist_entries(m3u) == [
        ("Radio Bob", "https://stream.example/bob.mp3"),
        ("Rock Antenne", "https://rock.example/live"),
        ("Mein Lied", "https://files.example/Mein_Lied.mp3"),
    ]
    pls = "[playlist]\nFile1=https://a.example/1\nTitle1=Eins\nFile2=https://b.example/2\nNumberOfEntries=2\n"
    assert parse_playlist_entries(pls) == [("Eins", "https://a.example/1"), ("2", "https://b.example/2")]


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
    assert parse_playlist_entries("#EXTINF:0, - RP MELLOW\nhttp://s.example/m") == [("RP MELLOW", "http://s.example/m")]
