"""HLS in Python: Variante waehlen, Teilstuecke der Reihe nach, Live-Nachladen."""

import pytest

from bot.cogs.music.hls import HlsError, HlsReader, Variant, choose_variant, looks_like_hls, parse_master, parse_media

MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1200000,CODECS="flac"
FLAC/program.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=330000,CODECS="mp4a.40.2"
320k/program.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=140000,CODECS="mp4a.40.2"
128k/program.m3u8
"""


def media(sequence, names, ended=False, init=None):
    lines = ["#EXTM3U", "#EXT-X-TARGETDURATION:10", f"#EXT-X-MEDIA-SEQUENCE:{sequence}"]
    if init:
        lines.append(f'#EXT-X-MAP:URI="{init}"')
    for name in names:
        lines += ["#EXTINF:10,", name]
    if ended:
        lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines)


class FakeServer:
    def __init__(self, playlists):
        self.playlists = playlists  # Adresse -> Liste von Texten (nacheinander abgerufen)
        self.fetched = []

    def get_text(self, url):
        texts = self.playlists[url]
        return url, texts.pop(0) if len(texts) > 1 else texts[0]

    def iter_bytes(self, url):
        self.fetched.append(url.rsplit("/", 1)[-1])
        yield url.rsplit("/", 1)[-1].encode() + b";"


def read_all(reader, limit=100):
    data = b""
    for _ in range(limit):
        chunk = reader.read(8192)
        if not chunk:
            break
        data += chunk
    return data


def test_master_picks_moderate_variant():
    variants = parse_master(MASTER, "https://r.example/hls/master.m3u8")
    assert [v.url for v in variants][1] == "https://r.example/hls/320k/program.m3u8"
    assert choose_variant(variants).bandwidth == 330000  # nicht FLAC, nicht die kleinste
    assert choose_variant([Variant("a", 900000), Variant("b", 600000)]).url == "b"  # sonst die kleinste
    assert parse_master(media(1, ["a.ts"]), "https://x/") == []


def test_media_playlist_parsing_and_unsupported():
    playlist = parse_media(media(7, ["a.aac", "https://cdn.example/b.aac"], ended=True, init="init.mp4"), "https://r.example/live/p.m3u8")
    assert playlist.sequence == 7 and playlist.ended and playlist.target_duration == 10
    assert playlist.segments == ["https://r.example/live/a.aac", "https://cdn.example/b.aac"]
    assert playlist.init == "https://r.example/live/init.mp4"
    with pytest.raises(HlsError, match="Verschlüsselt"):
        parse_media('#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="k"\na.ts', "https://x/")


def test_detects_hls_by_extension_or_content_type():
    assert looks_like_hls("https://x/live.m3u8?token=1", "")
    assert looks_like_hls("https://x/listen", "application/vnd.apple.mpegurl; charset=utf-8")
    assert not looks_like_hls("https://x/stream.mp3", "audio/mpeg")


def test_vod_plays_init_then_all_segments_once():
    server = FakeServer({"https://r.example/p.m3u8": [media(0, ["1.m4s", "2.m4s"], ended=True, init="init.mp4")]})
    reader = HlsReader("https://r.example/p.m3u8", server.get_text, server.iter_bytes, wait=lambda s: None)
    assert read_all(reader) == b"init.mp4;1.m4s;2.m4s;"


def test_live_starts_near_end_and_follows_new_segments():
    url = "https://r.example/hls/master.m3u8"
    live = "https://r.example/hls/320k/program.m3u8"
    server = FakeServer({
        url: [MASTER],
        live: [
            media(100, ["100.aac", "101.aac", "102.aac", "103.aac", "104.aac"]),
            media(102, ["102.aac", "103.aac", "104.aac", "105.aac"]),  # ein neues Teilstueck
            media(110, ["110.aac", "111.aac"], ended=True),  # zu langsam gewesen -> beim aeltesten vorhandenen weiter
        ],
    })
    reader = HlsReader(url, server.get_text, server.iter_bytes, wait=lambda s: None)
    assert reader.media_url == live
    assert read_all(reader) == b"102.aac;103.aac;104.aac;105.aac;110.aac;111.aac;"


def test_close_stops_reading():
    server = FakeServer({"https://r.example/p.m3u8": [media(0, ["1.ts", "2.ts"])]})
    reader = HlsReader("https://r.example/p.m3u8", server.get_text, server.iter_bytes, wait=lambda s: None)
    reader.close()
    assert reader.read(8192) == b""


def test_broken_segment_is_skipped_but_many_end_the_stream():
    class Flaky(FakeServer):
        def iter_bytes(self, url):
            if "bad" in url:
                raise OSError("timeout")
            yield from super().iter_bytes(url)

    server = Flaky({"https://r.example/p.m3u8": [media(0, ["1.ts", "bad1.ts", "2.ts"], ended=True)]})
    reader = HlsReader("https://r.example/p.m3u8", server.get_text, server.iter_bytes, wait=lambda s: None)
    assert read_all(reader) == b"1.ts;2.ts;"

    server = Flaky({"https://r.example/p.m3u8": [media(0, ["bad1.ts", "bad2.ts", "bad3.ts", "4.ts"], ended=True)]})
    reader = HlsReader("https://r.example/p.m3u8", server.get_text, server.iter_bytes, wait=lambda s: None)
    assert read_all(reader) == b""


def test_not_a_playlist_is_refused():
    with pytest.raises(HlsError):
        HlsReader("https://r.example/x.m3u8", lambda u: (u, "<html>"), lambda u: iter(()), wait=lambda s: None)
