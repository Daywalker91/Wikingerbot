"""Musik im Voice-Kanal (ersetzt Sinusbot): Radio-Streams, eigene Dateien
(data/music) und Podcasts. Bewusst ohne YouTube/Spotify und ohne Aufnahme.

FFmpeg: ein System-FFmpeg im PATH hat Vorrang, sonst das von imageio-ffmpeg
mitgelieferte - so laeuft es in AMP ohne Systempakete.
"""

import asyncio
import json
import logging
import shutil

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.cogs.music.player import GuildPlayer, Track
from bot.cogs.music.sources import (
    MUSIC_DIR,
    SourceError,
    check_public_url,
    check_public_urls,
    fetch_playlist_entries,
    needs_ffmpeg_network,
    open_stream,
    fetch_feed,
    files_in_folder,
    list_audio_files,
    list_folders,
    resolve_stream_url,
    safe_music_path,
    title_from_path,
)
from bot.core.base_cog import BaseCog
from bot.core.guild_config import get_config, set_config
from bot.core.permissions import Level, level_at_least, require_role, resolve_level

log = logging.getLogger(__name__)

IDLE_DISCONNECT_SECONDS = 300
STREAM_BEFORE_OPTIONS = (
    "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
    "-protocol_whitelist http,https,tcp,tls,crypto"
)
FILE_BEFORE_OPTIONS = "-protocol_whitelist file"
PIPE_BEFORE_OPTIONS = ""  # Stream kommt von Python ueber stdin


def voice_error_text(error: Exception) -> str:
    """Verstaendliche Meldung, warum der Bot nicht in den Sprachkanal kommt (und Log-Eintrag)."""
    if isinstance(error, asyncio.TimeoutError):
        log.warning(
            "Sprachverbindung: Zeitueberschreitung - die Anmeldung klappt, aber die Tonverbindung (UDP) "
            "kommt nicht durch. Meist blockiert eine Firewall/NAT ausgehendes UDP zu Discord "
            "(Ports 50000-65535) oder der Container hat kein UDP nach aussen."
        )
        return (
            "Ich komme in den Kanal, aber die Tonverbindung zu Discord kommt nicht zustande (Zeitüberschreitung). "
            "Das liegt meist an der Firewall/dem Netzwerk des Bot-Servers (ausgehendes UDP) – Details stehen im Log."
        )
    log.warning("Sprachverbindung fehlgeschlagen: %s", error)
    return "Ich komme nicht in den Sprachkanal (fehlen mir dort Rechte?)."


def opus_available() -> bool:
    """Ist die Opus-Bibliothek fuer discord.py geladen? Unter Windows bringt discord.py sie mit,
    unter Linux muss sie im System sein (libopus) - sonst False, dann kodiert FFmpeg selbst."""
    if discord.opus.is_loaded():
        return True
    import ctypes.util

    for name in filter(None, (ctypes.util.find_library("opus"), "libopus.so.0", "libopus.so")):
        try:
            discord.opus.load_opus(name)
            return True
        except Exception:
            continue
    return False


def ffmpeg_executable() -> str:
    system = shutil.which("ffmpeg")
    if system:
        return system
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


async def _get_json(guild_id: int, key: str) -> dict:
    try:
        return json.loads(await get_config(guild_id, key, "{}") or "{}")
    except json.JSONDecodeError:
        return {}


async def _set_json(guild: discord.Guild, key: str, value: dict) -> None:
    await set_config(guild.id, key, json.dumps(value), guild.name)


def normalize_url(url: str) -> str:
    """Zum Vergleich: ohne Leerzeichen, Schema/Host klein, ohne abschliessenden Schraegstrich."""
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, ""))


def station_conflict(stations: dict, name: str, url: str) -> str | None:
    """Warum dieser Sender nicht neu eingetragen wird - oder None. Schutz vor Doppelten."""
    wanted = normalize_url(url)
    for existing, existing_url in stations.items():
        if normalize_url(existing_url) == wanted:
            return f"Diese Adresse ist schon als **{existing}** eingetragen."
    if name.strip().casefold() in {n.casefold() for n in stations}:
        return f"Einen Sender **{name.strip()}** gibt es schon – anderen Namen wählen oder den alten erst entfernen."
    return None


def import_stations(stations: dict, entries: list[tuple[str, str]]) -> tuple[int, int]:
    """Eintraege einer Sender-Liste in `stations` (Name -> Adresse) uebernehmen.
    Gleiche Adresse = schon da; gleicher Name mit anderer Adresse bekommt " (2)" usw."""
    urls = {normalize_url(u) for u in stations.values()}
    added = known = 0
    for title, url in entries:
        if normalize_url(url) in urls:
            known += 1
            continue
        name, n = title[:100] or "Sender", 2
        while name in stations:
            name, n = f"{title[:94]} ({n})", n + 1
        stations[name] = url
        urls.add(normalize_url(url))
        added += 1
    return added, known


def _choices(values: list[str], current: str) -> list[app_commands.Choice[str]]:
    current = current.lower()
    return [app_commands.Choice(name=v[:100], value=v[:100]) for v in values if current in v.lower()][:25]


class MusicCog(BaseCog):
    """Radio, eigene Dateien und Podcasts im Voice-Kanal."""

    __cog_name__ = "music"
    __version__ = "1.0.0"
    __description__ = "Musik: Radio, Dateien, Podcasts"
    __author__ = "Daywalker91"

    music_group = app_commands.Group(name="musik", description="Musik im Voice-Kanal")
    config_group = app_commands.Group(name="musikconfig", description="Sender, Podcasts und Dateien verwalten")

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self.players: dict[int, GuildPlayer] = {}
        self._streams: dict[int, object] = {}  # Guild -> von Python geoeffneter Stream (Response)

    async def cog_load(self) -> None:
        # Ordner gleich anlegen, damit er im AMP-Dateimanager zu sehen ist
        MUSIC_DIR.mkdir(parents=True, exist_ok=True)
        if opus_available():
            log.info("Musik: Opus-Bibliothek gefunden, FFmpeg: %s", ffmpeg_executable())
        else:
            log.info("Musik: keine Opus-Bibliothek im System - FFmpeg (%s) kodiert selbst", ffmpeg_executable())
        self.idle_check.start()
        self.podcast_check.start()

    async def cog_unload(self) -> None:
        self.idle_check.cancel()
        self.podcast_check.cancel()
        for voice in list(self.bot.voice_clients):
            await voice.disconnect(force=True)

    def _player(self, guild_id: int) -> GuildPlayer:
        return self.players.setdefault(guild_id, GuildPlayer(guild_id))

    # --- Wiedergabe ------------------------------------------------------------

    def _source(self, track: Track, volume: float, stream=None) -> discord.AudioSource:
        """stream: von Python geoeffneter Response - FFmpeg liest dann von stdin (pipe)."""
        if stream is not None:
            source, before, pipe = stream.raw, PIPE_BEFORE_OPTIONS, True
        else:
            source, pipe = track.source, False
            before = FILE_BEFORE_OPTIONS if track.kind == "file" else STREAM_BEFORE_OPTIONS
        if opus_available():
            audio = discord.FFmpegPCMAudio(source, pipe=pipe, executable=ffmpeg_executable(), before_options=before, options="-vn")
            return discord.PCMVolumeTransformer(audio, volume=volume)
        # Ohne Opus-Bibliothek im System (z.B. schlanke Linux-Container): FFmpeg kodiert selbst
        # nach Opus. Lautstaerke dann als Filter - eine Aenderung gilt ab dem naechsten Titel.
        return discord.FFmpegOpusAudio(
            source, pipe=pipe, executable=ffmpeg_executable(), before_options=before, options=f"-vn -af volume={volume:.2f}"
        )

    async def _play_next(self, guild_id: int) -> None:
        guild = self.bot.get_guild(guild_id)
        voice = guild.voice_client if guild else None
        player = self._player(guild_id)
        if voice is None or not voice.is_connected() or voice.is_playing() or voice.is_paused():
            return
        while (track := player.next()) is not None:
            stream = None
            try:
                if track.kind == "stream" and not needs_ffmpeg_network(track.source):
                    stream = await asyncio.to_thread(open_stream, track.source)
                    self._close_stream(guild_id)
                    self._streams[guild_id] = stream
                source = self._source(track, player.volume, stream)
            except Exception as error:  # z.B. Datei inzwischen geloescht, Stream nicht erreichbar
                log.warning("Kann %s nicht abspielen: %s", track.title, error)
                if stream is not None:
                    stream.close()
                continue
            try:
                voice.play(source, after=lambda error, gid=guild_id: self._after(gid, error))
            except Exception as error:  # z.B. Opus fehlt, Verbindung gerade weg
                log.warning("Wiedergabe von %s nicht gestartet: %s", track.title, error)
                continue
            log.info("Spiele %s", track.title)
            return

    def _close_stream(self, guild_id: int) -> None:
        stream = self._streams.pop(guild_id, None)
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass

    def _after(self, guild_id: int, error: Exception | None) -> None:
        # laeuft im Audio-Thread von discord.py, nicht im Event-Loop
        if error:
            log.warning("Wiedergabe-Fehler: %s", error)
        self._close_stream(guild_id)
        asyncio.run_coroutine_threadsafe(self._play_next(guild_id), self.bot.loop)

    async def _voice_check(self, interaction: discord.Interaction) -> discord.VoiceChannel | None:
        """Kanal des Aufrufers - oder None mit Fehlermeldung."""
        member = interaction.user
        channel = member.voice.channel if isinstance(member, discord.Member) and member.voice else None
        if channel is None:
            await interaction.response.send_message("Geh zuerst in einen Voice-Kanal.", ephemeral=True, delete_after=20)
            return None
        voice = interaction.guild.voice_client
        if voice and voice.channel != channel and voice.is_playing() and not await self._is_mod(interaction):
            await interaction.response.send_message(
                f"Ich spiele gerade in {voice.channel.mention}.", ephemeral=True, delete_after=20
            )
            return None
        return channel

    async def _connect(self, guild: discord.Guild, channel: discord.VoiceChannel) -> discord.VoiceClient:
        voice = guild.voice_client
        if voice is None:
            return await channel.connect(self_deaf=True)
        if voice.channel != channel:
            await voice.move_to(channel)
        return voice

    async def _enqueue(self, interaction: discord.Interaction, channel: discord.VoiceChannel, tracks: list[Track]) -> None:
        """Nach defer(): verbinden, einreihen, ggf. starten, Rueckmeldung als Followup."""
        try:
            await self._connect(interaction.guild, channel)
        except (discord.ClientException, asyncio.TimeoutError, RuntimeError) as error:
            await interaction.followup.send(voice_error_text(error), ephemeral=True)
            return
        player = self._player(interaction.guild_id)
        was_idle = player.current is None
        added = player.add(*tracks)
        await self._play_next(interaction.guild_id)
        if not added:
            text = "Die Warteschlange ist voll."
        elif len(tracks) == 1:
            text = f"▶️ **{tracks[0].title}**" if was_idle else f"➕ In der Warteschlange: **{tracks[0].title}**"
        else:
            text = f"➕ {added} Titel eingereiht" + (" (Rest passte nicht mehr)" if added < len(tracks) else "")
        await interaction.followup.send(text, allowed_mentions=discord.AllowedMentions.none())

    # --- Fuer die Web-Oberflaeche (bot/cogs/music/api.py) ----------------------------

    async def resolve_tracks(
        self, guild_id: int, kind: str, name: str, user_id: int, *, episode: int = 0, shuffle: bool = False
    ) -> list[Track]:
        """Quelle -> Titel, wie bei den Slash-Commands. SourceError mit Meldung fuer den Nutzer."""
        if kind == "radio":
            stations = await _get_json(guild_id, "music_stations")
            if name not in stations:
                raise SourceError("Diesen Sender gibt es nicht.")
            return [Track(f"Radio: {name}", await resolve_stream_url(stations[name]), "stream", user_id, "Radio")]
        if kind == "file":
            path = safe_music_path(name)
            if not path.is_file():
                raise SourceError("Datei nicht gefunden.")
            return [Track(title_from_path(name), str(path), "file", user_id, "Datei")]
        if kind == "folder":
            files = files_in_folder(name)
            if not files:
                raise SourceError("In diesem Ordner liegen keine Audiodateien.")
            if shuffle:
                import random

                random.shuffle(files)
            return [Track(title_from_path(f), str(safe_music_path(f)), "file", user_id, "Datei") for f in files]
        if kind == "podcast":
            feeds = await _get_json(guild_id, "podcast_feeds")
            if name not in feeds:
                raise SourceError("Diesen Podcast gibt es nicht.")
            parsed = await fetch_feed(feeds[name]["url"])
            if not 0 <= episode < len(parsed.episodes):
                raise SourceError("Diese Folge gibt es nicht (mehr).")
            item = parsed.episodes[episode]
            await check_public_url(item.url)
            return [Track(f"{parsed.title}: {item.title}", item.url, "stream", user_id, "Podcast")]
        raise SourceError("Unbekannte Quelle.")

    async def start_tracks(self, guild: discord.Guild, channel: discord.VoiceChannel, tracks: list[Track]) -> int:
        """Verbinden, einreihen, ggf. starten. Gibt die Zahl eingereihter Titel zurueck."""
        await self._connect(guild, channel)
        added = self._player(guild.id).add(*tracks)
        await self._play_next(guild.id)
        return added

    def state(self, guild: discord.Guild) -> dict:
        player = self._player(guild.id)
        voice = guild.voice_client
        def track(t: Track | None):
            return {"title": t.title, "label": t.label} if t else None
        return {
            "connected": voice is not None,
            "channel_id": str(voice.channel.id) if voice else None,
            "channel_name": voice.channel.name if voice else None,
            "paused": bool(voice and voice.is_paused()),
            "current": track(player.current),
            "queue": [track(t) for t in list(player.queue)[:50]],
            "queue_length": len(player.queue),
            "volume": round(player.volume * 100),
        }

    async def control(self, guild: discord.Guild, action: str, value: int | None = None) -> None:
        voice = guild.voice_client
        player = self._player(guild.id)
        if action == "volume" and value is not None:
            volume = player.set_volume(value)
            if voice and isinstance(voice.source, discord.PCMVolumeTransformer):
                voice.source.volume = volume
            return
        if voice is None:
            raise SourceError("Ich spiele gerade nichts.")
        if action == "pause" and voice.is_playing():
            voice.pause()
        elif action == "resume" and voice.is_paused():
            voice.resume()
        elif action == "skip":
            voice.stop()
        elif action == "shuffle":
            player.shuffle()
        elif action == "stop":
            player.clear()
            await voice.disconnect()

    async def _is_mod(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            return False
        if member.guild_permissions.administrator:
            return True
        return level_at_least(await resolve_level(interaction.guild_id, [r.id for r in member.roles]), Level.MOD)

    async def _control_check(self, interaction: discord.Interaction) -> discord.VoiceClient | None:
        """Steuern darf, wer im selben Voice-Kanal ist - Mods immer."""
        voice = interaction.guild.voice_client
        if voice is None:
            await interaction.response.send_message("Ich spiele gerade nichts.", ephemeral=True, delete_after=20)
            return None
        member = interaction.user
        same_channel = isinstance(member, discord.Member) and member.voice and member.voice.channel == voice.channel
        if not same_channel and not await self._is_mod(interaction):
            await interaction.response.send_message(
                f"Dafür musst du in {voice.channel.mention} sein.", ephemeral=True, delete_after=20
            )
            return None
        return voice

    # --- Hintergrund ----------------------------------------------------------------

    @tasks.loop(seconds=60)
    async def idle_check(self) -> None:
        """Verlaesst den Kanal, wenn niemand mehr zuhoert oder lange nichts lief."""
        for voice in list(self.bot.voice_clients):
            listeners = [m for m in voice.channel.members if not m.bot]
            player = self._player(voice.guild.id)
            idle = not voice.is_playing() and not voice.is_paused() and player.idle_seconds() > IDLE_DISCONNECT_SECONDS
            if not listeners or idle:
                player.clear()
                await voice.disconnect()

    @idle_check.before_loop
    async def _before_idle(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=30)
    async def podcast_check(self) -> None:
        """Kuendigt neue Podcast-Folgen an (nur Feeds mit Ankuendigungs-Kanal)."""
        for guild in self.bot.guilds:
            feeds = await _get_json(guild.id, "podcast_feeds")
            changed = False
            for name, data in feeds.items():
                if not data.get("channel_id"):
                    continue
                try:
                    feed = await fetch_feed(data["url"], use_cache=False)
                except Exception as error:
                    log.info("Podcast %s nicht abrufbar: %s", name, error)
                    continue
                if not feed.episodes:
                    continue
                newest = feed.episodes[0]
                if data.get("last_guid") == newest.guid:
                    continue
                first_check = data.get("last_guid") is None
                data["last_guid"] = newest.guid
                changed = True
                if first_check:
                    continue  # beim ersten Mal nur merken, nicht die alte Folge ankuendigen
                channel = guild.get_channel(int(data["channel_id"]))
                if isinstance(channel, discord.TextChannel):
                    embed = discord.Embed(
                        title=f"🎙️ Neue Folge: {newest.title}"[:256],
                        description=f"**{feed.title}**{' · ' + newest.published if newest.published else ''}\n"
                        f"Anhören: `/musik podcast feed:{name}`",
                        color=0x8B5A2B,
                    )
                    try:
                        await channel.send(embed=embed)
                    except discord.HTTPException as error:
                        log.warning("Podcast-Ankuendigung fehlgeschlagen: %s", error)
            if changed:
                await _set_json(guild, "podcast_feeds", feeds)

    @podcast_check.before_loop
    async def _before_podcast(self) -> None:
        await self.bot.wait_until_ready()

    # --- Autocomplete ---------------------------------------------------------------

    async def _ac_station(self, interaction: discord.Interaction, current: str):
        return _choices(sorted(await _get_json(interaction.guild_id, "music_stations")), current)

    async def _ac_file(self, interaction: discord.Interaction, current: str):
        return _choices(list_audio_files(), current)

    async def _ac_folder(self, interaction: discord.Interaction, current: str):
        return _choices(list_folders(), current)

    async def _ac_feed(self, interaction: discord.Interaction, current: str):
        return _choices(sorted(await _get_json(interaction.guild_id, "podcast_feeds")), current)

    async def _ac_episode(self, interaction: discord.Interaction, current: str):
        feeds = await _get_json(interaction.guild_id, "podcast_feeds")
        data = feeds.get(getattr(interaction.namespace, "feed", None) or "")
        if not data:
            return []
        try:
            feed = await fetch_feed(data["url"])
        except Exception:
            return []
        current = current.lower()
        choices = []
        for index, episode in enumerate(feed.episodes[:100]):
            label = f"{episode.published} {episode.title}".strip()
            if current in label.lower():
                choices.append(app_commands.Choice(name=label[:100], value=str(index)))
        return choices[:25]

    # --- /musik ---------------------------------------------------------------------

    @music_group.command(name="radio", description="Spielt einen eingetragenen Radiosender")
    @app_commands.autocomplete(sender=_ac_station)
    async def play_radio(self, interaction: discord.Interaction, sender: str) -> None:
        stations = await _get_json(interaction.guild_id, "music_stations")
        if sender not in stations:
            await interaction.response.send_message(
                "Diesen Sender gibt es nicht – Liste mit `/musikconfig sender_liste`.", ephemeral=True, delete_after=20
            )
            return
        channel = await self._voice_check(interaction)
        if channel is None:
            return
        await interaction.response.defer(thinking=True)
        try:
            url = await resolve_stream_url(stations[sender])
        except Exception as error:
            await interaction.followup.send(f"Sender nicht erreichbar: {error}", ephemeral=True)
            return
        await self._enqueue(interaction, channel, [Track(f"Radio: {sender}", url, "stream", interaction.user.id, "Radio")])

    @music_group.command(name="datei", description="Spielt eine eigene Datei aus data/music")
    @app_commands.autocomplete(datei=_ac_file)
    async def play_file(self, interaction: discord.Interaction, datei: str) -> None:
        try:
            path = safe_music_path(datei)
        except SourceError as error:
            await interaction.response.send_message(str(error), ephemeral=True, delete_after=20)
            return
        if not path.is_file():
            await interaction.response.send_message("Datei nicht gefunden.", ephemeral=True, delete_after=20)
            return
        channel = await self._voice_check(interaction)
        if channel is None:
            return
        await interaction.response.defer(thinking=True)
        await self._enqueue(interaction, channel, [Track(title_from_path(datei), str(path), "file", interaction.user.id, "Datei")])

    @music_group.command(name="ordner", description="Reiht alle Dateien eines Ordners ein")
    @app_commands.describe(ordner="Unterordner von data/music (. = Hauptordner)", zufall="Zufaellige Reihenfolge")
    @app_commands.autocomplete(ordner=_ac_folder)
    async def play_folder(self, interaction: discord.Interaction, ordner: str, zufall: bool = False) -> None:
        files = files_in_folder(ordner)
        if not files:
            await interaction.response.send_message("In diesem Ordner liegen keine Audiodateien.", ephemeral=True, delete_after=20)
            return
        channel = await self._voice_check(interaction)
        if channel is None:
            return
        await interaction.response.defer(thinking=True)
        if zufall:
            import random

            random.shuffle(files)
        tracks = [Track(title_from_path(f), str(safe_music_path(f)), "file", interaction.user.id, "Datei") for f in files]
        await self._enqueue(interaction, channel, tracks)

    @music_group.command(name="url", description="Spielt einen Stream oder eine Audiodatei von einer Adresse")
    @app_commands.describe(url="http(s)-Adresse eines Streams, einer .m3u/.pls-Liste oder einer Audiodatei")
    @require_role(Level.MOD)
    async def play_url(self, interaction: discord.Interaction, url: str) -> None:
        channel = await self._voice_check(interaction)
        if channel is None:
            return
        await interaction.response.defer(thinking=True)
        try:
            await check_public_url(url)
            stream = await resolve_stream_url(url)
            await check_public_url(stream)
        except SourceError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        except Exception as error:
            await interaction.followup.send(f"Adresse nicht abrufbar: {error}", ephemeral=True)
            return
        await self._enqueue(interaction, channel, [Track(url.rsplit("/", 1)[-1][:80] or url, stream, "stream", interaction.user.id, "URL")])

    @music_group.command(name="playlist", description="Reiht alle Titel einer .m3u/.pls-Playlist ein (z.B. von GitHub, Raw-Adresse)")
    @app_commands.describe(url="http(s)-Adresse der Playlist", zufall="In zufaelliger Reihenfolge")
    @require_role(Level.MOD)
    async def play_playlist(self, interaction: discord.Interaction, url: str, zufall: bool = False) -> None:
        channel = await self._voice_check(interaction)
        if channel is None:
            return
        await interaction.response.defer(thinking=True)
        try:
            entries = await fetch_playlist_entries(url)
            await check_public_urls([u for _, u in entries])
        except SourceError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        except Exception as error:
            await interaction.followup.send(f"Playlist nicht abrufbar: {error}", ephemeral=True)
            return
        if zufall:
            import random

            random.shuffle(entries)
        tracks = [Track(title, address, "stream", interaction.user.id, "Playlist") for title, address in entries]
        await self._enqueue(interaction, channel, tracks)

    @music_group.command(name="podcast", description="Spielt eine Podcast-Folge (ohne Auswahl: die neueste)")
    @app_commands.autocomplete(feed=_ac_feed, folge=_ac_episode)
    async def play_podcast(self, interaction: discord.Interaction, feed: str, folge: str | None = None) -> None:
        feeds = await _get_json(interaction.guild_id, "podcast_feeds")
        if feed not in feeds:
            await interaction.response.send_message("Diesen Podcast gibt es nicht.", ephemeral=True, delete_after=20)
            return
        channel = await self._voice_check(interaction)
        if channel is None:
            return
        await interaction.response.defer(thinking=True)
        try:
            parsed = await fetch_feed(feeds[feed]["url"])
            index = int(folge) if folge and folge.isdigit() else 0
            episode = parsed.episodes[index]
            await check_public_url(episode.url)
        except IndexError:
            await interaction.followup.send("Diese Folge gibt es nicht (mehr).", ephemeral=True)
            return
        except Exception as error:
            await interaction.followup.send(f"Podcast nicht abrufbar: {error}", ephemeral=True)
            return
        await self._enqueue(
            interaction, channel, [Track(f"{parsed.title}: {episode.title}", episode.url, "stream", interaction.user.id, "Podcast")]
        )

    @music_group.command(name="pause", description="Pausiert die Wiedergabe")
    async def pause(self, interaction: discord.Interaction) -> None:
        voice = await self._control_check(interaction)
        if voice and voice.is_playing():
            voice.pause()
            await interaction.response.send_message("⏸️ Pausiert.")
        elif voice:
            await interaction.response.send_message("Es läuft gerade nichts.", ephemeral=True, delete_after=20)

    @music_group.command(name="weiter", description="Setzt die Wiedergabe fort")
    async def resume(self, interaction: discord.Interaction) -> None:
        voice = await self._control_check(interaction)
        if voice and voice.is_paused():
            voice.resume()
            await interaction.response.send_message("▶️ Weiter.")
        elif voice:
            await interaction.response.send_message("Es ist nichts pausiert.", ephemeral=True, delete_after=20)

    @music_group.command(name="skip", description="Springt zum naechsten Titel")
    async def skip(self, interaction: discord.Interaction) -> None:
        voice = await self._control_check(interaction)
        if voice:
            voice.stop()  # after-Callback startet den naechsten Titel
            await interaction.response.send_message("⏭️ Übersprungen.")

    @music_group.command(name="stopp", description="Stoppt, leert die Warteschlange und verlaesst den Kanal")
    async def stop(self, interaction: discord.Interaction) -> None:
        voice = await self._control_check(interaction)
        if voice:
            self._player(interaction.guild_id).clear()
            await voice.disconnect()
            await interaction.response.send_message("⏹️ Gestoppt.")

    @music_group.command(name="lautstaerke", description="Lautstaerke 0-100 (Standard 50)")
    async def volume(self, interaction: discord.Interaction, wert: app_commands.Range[int, 0, 100]) -> None:
        voice = await self._control_check(interaction)
        if voice is None:
            return
        volume = self._player(interaction.guild_id).set_volume(wert)
        if isinstance(voice.source, discord.PCMVolumeTransformer):
            voice.source.volume = volume
        await interaction.response.send_message(f"🔊 Lautstärke {wert}.")

    @music_group.command(name="mischen", description="Mischt die Warteschlange")
    async def shuffle(self, interaction: discord.Interaction) -> None:
        if await self._control_check(interaction):
            self._player(interaction.guild_id).shuffle()
            await interaction.response.send_message("🔀 Gemischt.")

    @music_group.command(name="warteschlange", description="Zeigt, was laeuft und was als Naechstes kommt")
    async def queue(self, interaction: discord.Interaction) -> None:
        player = self._player(interaction.guild_id)
        if player.current is None and not player.queue:
            await interaction.response.send_message("Die Warteschlange ist leer.", ephemeral=True, delete_after=20)
            return
        lines = []
        if player.current:
            lines.append(f"▶️ **{player.current.title}** ({player.current.label})")
        for number, track in enumerate(list(player.queue)[:10], start=1):
            lines.append(f"{number}. {track.title}")
        if len(player.queue) > 10:
            lines.append(f"… und {len(player.queue) - 10} weitere")
        lines.append(f"🔊 {round(player.volume * 100)}")
        await interaction.response.send_message("\n".join(lines)[:2000], ephemeral=True)

    # --- /musikconfig ---------------------------------------------------------------

    @config_group.command(name="sender_hinzufuegen", description="Traegt einen Radiosender ein")
    @app_commands.describe(name="Anzeigename", url="Stream-Adresse oder .m3u/.pls-Liste des Senders")
    @require_role(Level.ADMIN)
    async def station_add(self, interaction: discord.Interaction, name: str, url: str) -> None:
        if not url.startswith(("http://", "https://")):
            await interaction.response.send_message("Die Adresse muss mit http:// oder https:// beginnen.", ephemeral=True)
            return
        stations = await _get_json(interaction.guild_id, "music_stations")
        conflict = station_conflict(stations, name, url)
        if conflict:
            await interaction.response.send_message(conflict, ephemeral=True, delete_after=30)
            return
        stations[name.strip()[:100]] = url.strip()
        await _set_json(interaction.guild, "music_stations", stations)
        await interaction.response.send_message(f"Sender **{name}** eingetragen.", ephemeral=True, delete_after=20)

    @config_group.command(name="sender_import", description="Traegt alle Sender einer .m3u/.pls-Liste ein (z.B. von GitHub, Raw-Adresse)")
    @app_commands.describe(url="http(s)-Adresse der Sender-Liste")
    @require_role(Level.ADMIN)
    async def station_import(self, interaction: discord.Interaction, url: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            entries = await fetch_playlist_entries(url)
        except SourceError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        except Exception as error:
            await interaction.followup.send(f"Liste nicht abrufbar: {error}", ephemeral=True)
            return
        stations = await _get_json(interaction.guild_id, "music_stations")
        added, known = import_stations(stations, entries)
        await _set_json(interaction.guild, "music_stations", stations)
        await interaction.followup.send(
            f"{added} Sender eingetragen" + (f", {known} waren schon da" if known else "") + ". Abspielen mit `/musik radio sender:`.",
            ephemeral=True,
        )

    @config_group.command(name="sender_entfernen", description="Entfernt einen Radiosender")
    @app_commands.autocomplete(name=_ac_station)
    @require_role(Level.ADMIN)
    async def station_remove(self, interaction: discord.Interaction, name: str) -> None:
        stations = await _get_json(interaction.guild_id, "music_stations")
        removed = stations.pop(name, None)
        await _set_json(interaction.guild, "music_stations", stations)
        text = f"Sender **{name}** entfernt." if removed else "Diesen Sender gibt es nicht."
        await interaction.response.send_message(text, ephemeral=True, delete_after=20)

    @config_group.command(name="sender_liste", description="Zeigt die eingetragenen Radiosender")
    async def station_list(self, interaction: discord.Interaction) -> None:
        stations = await _get_json(interaction.guild_id, "music_stations")
        text = "\n".join(f"- **{n}**" for n in sorted(stations)) or "Noch keine Sender eingetragen."
        await interaction.response.send_message(text[:2000], ephemeral=True)

    @config_group.command(name="podcast_abonnieren", description="Traegt einen Podcast (RSS-Feed) ein")
    @app_commands.describe(name="Kurzname fuer die Auswahl", url="Adresse des RSS-Feeds")
    @require_role(Level.ADMIN)
    async def podcast_add(self, interaction: discord.Interaction, name: str, url: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            feed = await fetch_feed(url, use_cache=False)
        except Exception as error:
            await interaction.followup.send(f"Feed nicht nutzbar: {error}", ephemeral=True)
            return
        feeds = await _get_json(interaction.guild_id, "podcast_feeds")
        feeds[name[:100]] = {"url": url, "channel_id": None, "last_guid": feed.episodes[0].guid if feed.episodes else None}
        await _set_json(interaction.guild, "podcast_feeds", feeds)
        await interaction.followup.send(
            f"**{feed.title}** eingetragen ({len(feed.episodes)} Folgen). Neue Folgen ankündigen: "
            "`/musikconfig podcast_ankuendigen`.",
            ephemeral=True,
        )

    @config_group.command(name="podcast_entfernen", description="Entfernt einen Podcast")
    @app_commands.autocomplete(name=_ac_feed)
    @require_role(Level.ADMIN)
    async def podcast_remove(self, interaction: discord.Interaction, name: str) -> None:
        feeds = await _get_json(interaction.guild_id, "podcast_feeds")
        removed = feeds.pop(name, None)
        await _set_json(interaction.guild, "podcast_feeds", feeds)
        text = f"Podcast **{name}** entfernt." if removed else "Diesen Podcast gibt es nicht."
        await interaction.response.send_message(text, ephemeral=True, delete_after=20)

    @config_group.command(name="podcast_ankuendigen", description="Neue Folgen in einem Kanal ankuendigen (ohne Kanal: aus)")
    @app_commands.autocomplete(name=_ac_feed)
    @require_role(Level.ADMIN)
    async def podcast_announce(
        self, interaction: discord.Interaction, name: str, kanal: discord.TextChannel | None = None
    ) -> None:
        feeds = await _get_json(interaction.guild_id, "podcast_feeds")
        if name not in feeds:
            await interaction.response.send_message("Diesen Podcast gibt es nicht.", ephemeral=True, delete_after=20)
            return
        feeds[name]["channel_id"] = kanal.id if kanal else None
        await _set_json(interaction.guild, "podcast_feeds", feeds)
        text = f"Neue Folgen von **{name}** werden in {kanal.mention} angekündigt (Prüfung alle 30 Minuten)." if kanal else f"Ankündigung für **{name}** ist aus."
        await interaction.response.send_message(text, ephemeral=True, delete_after=20)

    @config_group.command(name="dateien", description="Zeigt, wo eigene Musikdateien hingehoeren")
    @require_role(Level.ADMIN)
    async def files_info(self, interaction: discord.Interaction) -> None:
        files = list_audio_files()
        folders = [f for f in list_folders() if f != "."]
        await interaction.response.send_message(
            f"Eigene Dateien gehören nach `{MUSIC_DIR}` (in AMP: Dateimanager → `Wikingerbot-main/data/music`, "
            f"Unterordner = Playlisten). Erlaubt: mp3, ogg, opus, flac, wav, m4a, aac.\n"
            f"Gefunden: {len(files)} Dateien in {len(folders)} Unterordnern.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MusicCog(bot))
