"""Nachrichten in Ankuendigungskanaelen veroeffentlichen (gemeinsam fuer news, events).

In einem Ankuendigungskanal erreicht eine Nachricht folgende Server erst, wenn sie
veroeffentlicht ist. Spaetere Bearbeitungen gehen danach von selbst mit.
"""

import logging

import discord

log = logging.getLogger("wikingerbot.community")


async def publish_if_announcement(message: discord.Message) -> bool:
    """Veroeffentlicht die Nachricht, wenn sie in einem Ankuendigungskanal steht.

    Fehler (fehlendes Recht, Discords Limit von etwa 10 pro Stunde und Kanal) werden
    nur geloggt - die Nachricht steht trotzdem im Kanal.
    """
    if getattr(message.channel, "type", None) != discord.ChannelType.news:
        return False
    try:
        await message.publish()
    except discord.HTTPException as error:
        log.warning("Nachricht %s in #%s nicht veroeffentlicht: %s", message.id, message.channel, error)
        return False
    return True
