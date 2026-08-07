"""Discord command layer for Rift generation and exploration."""

from __future__ import annotations

import discord
from discord.ext import commands

from .display import (
    render_claim_summary,
    render_clear_result,
    render_dungeon_map,
    render_rift_listings,
    render_travel_result,
)
from .loot import render_ledger
from .navigation import NavigationError
from .service import ClaimError, RiftActionError, RiftService


# The name of the GM/Moderator role of the server
RIFT_MODERATOR_ROLE_NAME = "GM"


async def _send_text(ctx: commands.Context, text: str) -> None:
    """Send text in Discord-safe chunks without embedding command logic."""

    remaining = text
    while len(remaining) > 2000:
        split_at = remaining.rfind("\n", 0, 2000)
        if split_at <= 0:
            split_at = 2000
        await ctx.send(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")
    if remaining:
        await ctx.send(remaining)


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
                self.rift_id, interaction.user.id
            )
        except ClaimError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        await interaction.followup.send(
            render_claim_summary(rift, dungeon), ephemeral=True
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

    @commands.hybrid_group(name="rift", invoke_without_command=True)
    async def rift(self, ctx: commands.Context) -> None:
        """Manage and explore Rifts."""

        await ctx.send_help(ctx.command)

    @rift.command(name="list")
    async def list_rifts(
        self,
        ctx: commands.Context,
        *,
        owner: str | None = None,
    ) -> None:
        """List active Rifts, optionally filtered by owner or region."""

        listings = self.service.repository.list_active_rifts(owner=owner)
        heading = f"Active Rifts — {owner}:" if owner else "Active Rifts:"
        await _send_text(ctx, render_rift_listings(listings, heading=heading))

    @rift.command(name="claim")
    async def claim_rift(self, ctx: commands.Context, rift_id: str) -> None:
        """Claim a Rift and generate its dungeon."""

        try:
            rift, dungeon = self.service.claim_and_generate(
                rift_id, ctx.author.id
            )
        except ClaimError as error:
            await ctx.send(str(error))
            return
        await _send_text(
            ctx,
            render_claim_summary(rift, dungeon)
            + "\n"
            + render_dungeon_map(dungeon),
        )

    @rift.command(name="navigate", aliases=["move"])
    async def navigate_rift(
        self,
        ctx: commands.Context,
        rift_id: str,
        room_id: int,
    ) -> None:
        """Navigate the claimed Rift to a visible room."""

        try:
            _, dungeon, result = self.service.navigate(
                rift_id, room_id, ctx.author.id
            )
        except (RiftActionError, NavigationError) as error:
            await ctx.send(str(error))
            return
        await _send_text(
            ctx,
            render_travel_result(result) + "\n" + render_dungeon_map(dungeon),
        )

    @rift.command(name="clear")
    async def clear_rift_room(
        self,
        ctx: commands.Context,
        rift_id: str,
    ) -> None:
        """Clear the current room in a claimed Rift."""

        try:
            _, dungeon, result = self.service.clear_current_room(
                rift_id, ctx.author.id
            )
        except (RiftActionError, ValueError) as error:
            await ctx.send(str(error))
            return
        output = render_clear_result(result)
        if result.boss_cleared:
            output += "\n\n" + render_ledger(dungeon)
        await _send_text(ctx, output)

    @rift.command(name="fail")
    @commands.has_role(RIFT_MODERATOR_ROLE_NAME)
    async def fail_rift(self, ctx: commands.Context, rift_id: str) -> None:
        """Mark a Rift failed. Requires the configured moderator role."""

        try:
            rift = self.service.fail_rift(rift_id)
        except RiftActionError as error:
            await ctx.send(str(error))
            return
        await ctx.send(f"Rift {rift.rift_id} has been marked failed.")

    @rift.command(name="unclaim")
    @commands.has_role(RIFT_MODERATOR_ROLE_NAME)
    async def unclaim_rift(self, ctx: commands.Context, rift_id: str) -> None:
        """Reset a claimed Rift. Requires the configured moderator role."""

        try:
            rift = self.service.unclaim_rift(rift_id)
        except RiftActionError as error:
            await ctx.send(str(error))
            return
        await ctx.send(f"Rift {rift.rift_id} is available again.")

    async def cog_command_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None:
        if isinstance(error, commands.MissingRole):
            await ctx.send(
                f"This command requires the {RIFT_MODERATOR_ROLE_NAME} role."
            )
            return
        raise error


async def setup(bot: commands.Bot) -> None:
    """Load the cog when the bot exposes a configured RiftService."""

    service = getattr(bot, "rift_service", None)
    if not isinstance(service, RiftService):
        raise RuntimeError("bot.rift_service must be configured before loading.")
    await bot.add_cog(RiftCog(bot, service))
