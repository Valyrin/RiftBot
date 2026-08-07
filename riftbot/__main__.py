from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

from .data import load_motifs, load_pokedex, load_rooms
from .repository import RiftRepository
from .scheduler import DailyRiftScheduler, ScheduleSettings
from .service import RiftService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RiftBot(commands.Bot):
    def __init__(
        self,
        service: RiftService,
        scheduler: DailyRiftScheduler,
        *,
        command_prefix: str,
        sync_commands: bool,
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=command_prefix, intents=intents)
        self.rift_service = service
        self.rift_scheduler = scheduler
        self.sync_commands = sync_commands
        self.scheduler_task: asyncio.Task[None] | None = None

    async def setup_hook(self) -> None:
        await self.load_extension("riftbot.discord_cog")
        if self.sync_commands:
            await self.tree.sync()
        self.scheduler_task = asyncio.create_task(
            self.rift_scheduler.run(),
            name="daily-rift-scheduler",
        )

    async def close(self) -> None:
        if self.scheduler_task is not None:
            self.scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.scheduler_task
        await super().close()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def create_bot() -> RiftBot:
    """Build the Discord application without connecting to Discord."""

    load_dotenv(PROJECT_ROOT / ".env")
    database_path = Path(os.getenv("RIFT_DATABASE", "riftbot.sqlite3"))
    if not database_path.is_absolute():
        database_path = PROJECT_ROOT / database_path

    motifs = load_motifs(PROJECT_ROOT / "data" / "motifs.json")
    pokedex = load_pokedex(PROJECT_ROOT / "data" / "pokedex.json")
    rooms = load_rooms(PROJECT_ROOT / "data" / "rooms.json")

    repository = RiftRepository(database_path)
    service = RiftService(repository, rooms, pokedex)
    scheduler = DailyRiftScheduler(
        repository,
        motifs,
        ScheduleSettings(
            hour=int(os.getenv("RIFT_SCHEDULE_HOUR", "0")),
            minute=int(os.getenv("RIFT_SCHEDULE_MINUTE", "0")),
            timezone_name=os.getenv(
                "RIFT_TIMEZONE", "America/Los_Angeles"
            ),
        ),
    )
    return RiftBot(
        service,
        scheduler,
        command_prefix=os.getenv("COMMAND_PREFIX", "!"),
        sync_commands=_env_bool("SYNC_COMMANDS", True),
    )


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "DISCORD_TOKEN is missing. Add it to the project's .env file."
        )
    create_bot().run(token)


if __name__ == "__main__":
    main()
