"""Discord.py integration scaffold.

This file is intentionally lightweight. Wire its IDs, permissions, and command names
into your existing bot.
"""

from __future__ import annotations

import discord
from discord.ext import commands

from .loot import render_ledger
from .service import ClaimError, RiftService


class ClaimRiftButton(discord.ui.Button):
    def __init__(self, rift_id: str):
        super().__init__(
            label="Claim Rift",
            style=discord.ButtonStyle.primary,
            custom_id=f"rift_claim:{rift_id}",
        )
        self.rift_id = rift_id

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, RiftListingView):
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            rift, dungeon = view.service.claim_and_generate(
                self.rift_id,
                interaction.user.id,
            )
        except ClaimError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        source_message = interaction.message
        if source_message is None:
            await interaction.followup.send(
                "The Rift was claimed, but its listing message was unavailable.",
                ephemeral=True,
            )
            return

        # Thread creation happens only after claim and generation succeed.
        thread = await source_message.create_thread(
            name=f"{rift.rift_level}-Rank {rift.motif.name} Rift",
            auto_archive_duration=1440,
        )
        rift.thread_id = thread.id
        view.service.repository.save_rift(rift)

        await thread.send(
            f"Rift claimed by {interaction.user.mention}.\n"
            f"Entrance Room: **{dungeon.rooms[dungeon.entrance_room_id].definition.name}**"
        )
        await interaction.followup.send(
            f"Rift claimed. Thread created: {thread.mention}",
            ephemeral=True,
        )


class RiftListingView(discord.ui.View):
    def __init__(self, service: RiftService, rift_id: str):
        super().__init__(timeout=None)
        self.service = service
        self.add_item(ClaimRiftButton(rift_id))


class RiftCog(commands.Cog):
    def __init__(self, bot: commands.Bot, service: RiftService):
        self.bot = bot
        self.service = service
