from __future__ import annotations

from datetime import datetime, timezone

from .generation import generate_dungeon
from .models import PokedexEntry, RiftListing, RiftStatus, RoomDefinition
from .repository import RiftRepository


class ClaimError(RuntimeError):
    pass


class RiftService:
    def __init__(
        self,
        repository: RiftRepository,
        room_entries: list[RoomDefinition],
        pokedex: list[PokedexEntry],
    ) -> None:
        self.repository = repository
        self.room_entries = room_entries
        self.pokedex = pokedex

    def claim_and_generate(
        self,
        rift_id: str,
        user_id: int,
    ):
        if not self.repository.claim_available(rift_id, user_id):
            raise ClaimError("That Rift is unavailable or already claimed.")

        rift = self.repository.get_rift(rift_id)
        if rift is None:
            raise ClaimError("The claimed Rift could not be loaded.")

        try:
            dungeon = generate_dungeon(
                rift,
                self.room_entries,
                self.pokedex,
            )
            self.repository.save_dungeon(dungeon)
            rift.status = RiftStatus.READY
            rift.dungeon_id = dungeon.dungeon_id
            self.repository.save_rift(rift)
            return rift, dungeon
        except Exception:
            rift.status = RiftStatus.FAILED
            self.repository.save_rift(rift)
            raise

    def complete_rift(self, rift: RiftListing) -> None:
        rift.status = RiftStatus.COMPLETED
        self.repository.save_rift(rift)

    def expire_available_rifts(self) -> list[str]:
        return self.repository.expire_available(
            datetime.now(timezone.utc)
        )
