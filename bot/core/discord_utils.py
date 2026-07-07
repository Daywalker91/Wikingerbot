import discord

MESSAGE_TIMEOUT = 20  # Sekunden, bis ephemere Bestaetigungen sich selbst loeschen


async def send_temp_followup(interaction: discord.Interaction, *args, **kwargs) -> None:
    """Wie interaction.followup.send, loescht sich aber nach MESSAGE_TIMEOUT von selbst.

    interaction.response.send_message() unterstuetzt delete_after nativ,
    Webhook.send() (also interaction.followup.send()) nicht - das wird hier
    nachgebaut, indem die zurueckgegebene Nachricht verzoegert geloescht wird.
    """
    msg = await interaction.followup.send(*args, **kwargs)
    if msg is not None:
        await msg.delete(delay=MESSAGE_TIMEOUT)
