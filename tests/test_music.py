"""music-Cog: Quellen, Warteschlange und ein echter FFmpeg-Lauf (ohne Discord)."""

import math
import struct
import wave

import pytest

from bot.cogs.music import sources
from bot.cogs.music.player import MAX_QUEUE, GuildPlayer, Track
from bot.cogs.music.sources import (
    SourceError,
    check_public_url,
    files_in_folder,
    is_public_ip,
    list_audio_files,
    list_folders,
    parse_feed,
    parse_playlist,
    safe_music_path,
    title_from_path,
)

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Wikinger-Funk</title>
  <item><title>Folge 2</title><guid>ep2</guid><pubDate>Fri, 02 Oct 2026 08:00:00 +0200</pubDate>
    <enclosure url="https://cdn.example.org/ep2.mp3" type="audio/mpeg" length="1"/></item>
  <item><title>Nur Text</title><guid>blog</guid></item>
  <item><title>Folge 1</title>
    <enclosure url="https://cdn.example.org/ep1.mp3" type="audio/mpeg" length="1"/></item>
</channel></rss>"""


def test_parse_playlist_m3u_and_pls():
    assert parse_playlist("#EXTM3U\n#EXTINF:-1,Sender\nhttp://stream.example.org/live\n") == "http://stream.example.org/live"
    assert parse_playlist("[playlist]\nNumberOfEntries=1\nFile1=https://s.example.org/a\nTitle1=x") == "https://s.example.org/a"
    assert parse_playlist("nix hier") is None


def test_parse_feed():
    feed = parse_feed(FEED)
    assert feed.title == "Wikinger-Funk"
    assert [e.title for e in feed.episodes] == ["Folge 2", "Folge 1"]  # Eintrag ohne Audio faellt raus
    assert feed.episodes[0].published == "02.10.2026"
    assert feed.episodes[1].guid == "https://cdn.example.org/ep1.mp3"  # ohne guid: URL


def test_parse_feed_rejects_garbage_and_entity_bombs():
    with pytest.raises(SourceError):
        parse_feed(b"kein xml")
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><rss><channel><title>&b;</title></channel></rss>'
    with pytest.raises(SourceError):
        parse_feed(bomb)


def test_is_public_ip():
    assert is_public_ip("1.1.1.1")
    for address in ("10.0.0.5", "192.168.1.5", "127.0.0.1", "169.254.1.1", "::1", "fd00::1", "224.0.0.1"):
        assert not is_public_ip(address), address


async def test_check_public_url_blocks_internal_and_other_schemes():
    for url in ("http://127.0.0.1/x", "http://localhost/x", "http://10.0.0.10:3306/", "file:///etc/passwd", "ftp://x/y"):
        with pytest.raises(SourceError):
            await check_public_url(url)


def test_local_files(tmp_path):
    (tmp_path / "Lieder").mkdir()
    (tmp_path / "Lieder" / "Met_und_Mut.mp3").write_bytes(b"x")
    (tmp_path / "Lieder" / "notiz.txt").write_text("x")
    (tmp_path / "Intro.ogg").write_bytes(b"x")

    assert list_audio_files(tmp_path) == ["Intro.ogg", "Lieder/Met_und_Mut.mp3"]
    assert list_folders(tmp_path) == [".", "Lieder"]
    assert files_in_folder("Lieder", tmp_path) == ["Lieder/Met_und_Mut.mp3"]
    assert files_in_folder(".", tmp_path) == ["Intro.ogg"]
    assert title_from_path("Lieder/Met_und_Mut.mp3") == "Met und Mut"


def test_safe_music_path_stays_inside(tmp_path):
    assert safe_music_path("a/b.mp3", tmp_path) == (tmp_path / "a" / "b.mp3").resolve()
    for evil in ("../../etc/passwd", "/etc/passwd", "..\\..\\x"):
        with pytest.raises(SourceError):
            safe_music_path(evil, tmp_path)


def test_player_queue():
    player = GuildPlayer(1)
    tracks = [Track(f"t{i}", f"s{i}", "stream", 1) for i in range(3)]
    assert player.add(*tracks) == 3
    assert player.next().title == "t0"
    assert player.idle_seconds() == 0
    assert player.set_volume(150) == 1.0 and player.set_volume(-5) == 0.0
    player.clear()
    assert player.current is None and not player.queue
    assert player.next() is None


def test_player_queue_limit():
    player = GuildPlayer(1)
    many = [Track("t", "s", "stream", 1)] * (MAX_QUEUE + 5)
    assert player.add(*many) == MAX_QUEUE
    assert player.add(Track("x", "y", "stream", 1)) == 0


def test_ffmpeg_decodes_a_local_file(tmp_path):
    """Echter Lauf: FFmpeg (System oder imageio-ffmpeg) dekodiert eine Datei so,
    wie der Cog es fuer Discord tut - 20-ms-PCM-Frames."""
    import discord

    from bot.cogs.music.cog import FILE_BEFORE_OPTIONS, ffmpeg_executable

    path = tmp_path / "ton.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 20))) for i in range(48000)))

    audio = discord.FFmpegPCMAudio(str(path), executable=ffmpeg_executable(), before_options=FILE_BEFORE_OPTIONS, options="-vn")
    try:
        frame = audio.read()
        assert len(frame) == discord.opus.Encoder.FRAME_SIZE  # 3840 Byte = 20 ms Stereo 48 kHz
    finally:
        audio.cleanup()


def test_music_dir_is_in_data():
    assert sources.MUSIC_DIR.parts[-2:] == ("data", "music")
