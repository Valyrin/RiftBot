from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from .generation import generate_daily_rifts
from .models import RiftMotif
from .repository import RiftRepository


@dataclass(frozen=True)
class ScheduleSettings:
    hour: int
    minute: int
    timezone_name: str

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)


class DailyRiftScheduler:
    """Small restart-safe scheduler.

    Call `run()` as an asyncio task. Daily generation is idempotent if the
    repository already contains Rifts generated on that date.
    """

    def __init__(
        self,
        repository: RiftRepository,
        motifs: list[RiftMotif],
        settings: ScheduleSettings,
    ) -> None:
        self.repository = repository
        self.motifs = motifs
        self.settings = settings
        self._last_date = None

    async def run(self) -> None:
        while True:
            now = datetime.now(timezone.utc)
            local = now.astimezone(self.settings.timezone)
            due = (
                local.hour > self.settings.hour
                or (
                    local.hour == self.settings.hour
                    and local.minute >= self.settings.minute
                )
            )

            if due and self._last_date != local.date():
                if not self.repository.has_generated_rifts_on(now.date()):
                    for rift in generate_daily_rifts(
                        self.motifs,
                        now=now,
                    ):
                        self.repository.save_rift(rift)
                self._last_date = local.date()

            self.repository.expire_available(now)
            await asyncio.sleep(60)
