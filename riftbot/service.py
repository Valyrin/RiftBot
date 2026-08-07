from __future__ import annotations

from datetime import datetime, timezone

from .generation import generate_dungeon
from .loot import ClearResult, clear_room
from .models import (
    GeneratedDungeon,
    PokedexEntry,
    RiftListing,
    RiftStatus,
    RoomDefinition,
)
from .navigation import TravelResult, travel_to_room
from .repository import RiftRepository


class ClaimError(RuntimeError):
    pass


class RiftActionError(RuntimeError):
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

    def _claimed_rift_and_dungeon(
        self,
        rift_id: str,
        user_id: int,
    ):
        rift = self.repository.get_rift(rift_id)
        if rift is None:
            raise RiftActionError("That Rift does not exist.")
        if rift.claimed_by_user_id != user_id:
            raise RiftActionError("Only the claimant can manage this Rift.")
        if rift.status not in {RiftStatus.READY, RiftStatus.ACTIVE}:
            raise RiftActionError("That Rift is not ready for exploration.")
        dungeon = self.repository.get_dungeon_for_rift(rift_id)
        if dungeon is None:
            raise RiftActionError("That Rift has no generated dungeon.")
        return rift, dungeon

    def navigate(
        self,
        rift_id: str,
        room_id: int,
        user_id: int,
    ) -> tuple[RiftListing, GeneratedDungeon, TravelResult]:
        rift, dungeon = self._claimed_rift_and_dungeon(rift_id, user_id)
        result = travel_to_room(dungeon, room_id)
        if rift.status is RiftStatus.READY:
            rift.status = RiftStatus.ACTIVE
            self.repository.save_rift(rift)
        self.repository.save_dungeon(dungeon)
        return rift, dungeon, result

    def clear_current_room(
        self,
        rift_id: str,
        user_id: int,
    ) -> tuple[RiftListing, GeneratedDungeon, ClearResult]:
        rift, dungeon = self._claimed_rift_and_dungeon(rift_id, user_id)
        room_id = dungeon.navigation.current_room_id
        result = clear_room(dungeon, room_id)
        if result.boss_cleared:
            rift.status = RiftStatus.COMPLETED
        elif rift.status is RiftStatus.READY:
            rift.status = RiftStatus.ACTIVE
        self.repository.save_dungeon(dungeon)
        self.repository.save_rift(rift)
        return rift, dungeon, result

    def fail_rift(self, rift_id: str) -> RiftListing:
        rift = self.repository.get_rift(rift_id)
        if rift is None:
            raise RiftActionError("That Rift does not exist.")
        if rift.status in {RiftStatus.COMPLETED, RiftStatus.EXPIRED}:
            raise RiftActionError("That Rift can no longer be failed.")
        rift.status = RiftStatus.FAILED
        self.repository.save_rift(rift)
        return rift

    def unclaim_rift(self, rift_id: str) -> RiftListing:
        rift = self.repository.get_rift(rift_id)
        if rift is None:
            raise RiftActionError("That Rift does not exist.")
        if rift.claimed_by_user_id is None:
            raise RiftActionError("That Rift is not claimed.")
        rift.status = RiftStatus.AVAILABLE
        rift.claimed_by_user_id = None
        rift.claimed_at = None
        rift.dungeon_id = None
        rift.thread_id = None
        self.repository.delete_dungeon_for_rift(rift_id)
        self.repository.save_rift(rift)
        return rift

    def expire_available_rifts(self) -> list[str]:
        return self.repository.expire_available(
            datetime.now(timezone.utc)
        )
