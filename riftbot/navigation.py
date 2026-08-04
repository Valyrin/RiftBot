from __future__ import annotations

from dataclasses import dataclass

from .loot import clear_room
from .models import GeneratedDungeon, RiftStatus, RoomState


class NavigationError(RuntimeError):
    pass


DIRECT_TRAVEL_STATES = {
    RoomState.SEEN,
    RoomState.VISITED,
    RoomState.CLEARED,
}


def room_state(dungeon: GeneratedDungeon, room_id: int) -> RoomState:
    progress = dungeon.navigation.room_progress[room_id]
    if room_id == dungeon.navigation.current_room_id:
        return RoomState.CURRENT
    if progress.locked:
        return RoomState.LOCKED
    if progress.cleared:
        return RoomState.CLEARED
    if progress.visited:
        return RoomState.VISITED
    if progress.seen:
        return RoomState.SEEN
    return RoomState.UNKNOWN


def reveal_adjacent(dungeon: GeneratedDungeon, room_id: int) -> None:
    for adjacent_id in dungeon.rooms[room_id].connected_room_ids:
        progress = dungeon.navigation.room_progress[adjacent_id]
        if not progress.locked:
            progress.seen = True


def lock_unvisited_rooms(dungeon: GeneratedDungeon) -> None:
    for room_id, progress in dungeon.navigation.room_progress.items():
        if room_id == dungeon.navigation.current_room_id:
            continue
        if not progress.visited and not progress.cleared:
            progress.locked = True


@dataclass(frozen=True)
class TravelResult:
    previous_room_id: int
    current_room_id: int
    first_visit: bool
    auto_cleared: bool
    boss_lock_triggered: bool


def travel_to_room(
    dungeon: GeneratedDungeon,
    room_id: int,
) -> TravelResult:
    if room_id not in dungeon.rooms:
        raise NavigationError("That room does not exist.")
    if room_id == dungeon.navigation.current_room_id:
        raise NavigationError("The party is already in that room.")

    state = room_state(dungeon, room_id)
    if state not in DIRECT_TRAVEL_STATES:
        if state is RoomState.UNKNOWN:
            raise NavigationError("That room is unknown.")
        if state is RoomState.LOCKED:
            raise NavigationError("That room is locked.")
        raise NavigationError("That room cannot be entered.")

    previous = dungeon.navigation.current_room_id
    progress = dungeon.navigation.room_progress[room_id]
    first_visit = not progress.visited

    dungeon.navigation.current_room_id = room_id
    progress.seen = True
    progress.visited = True
    reveal_adjacent(dungeon, room_id)

    boss_lock = False
    room = dungeon.rooms[room_id]
    if room.is_boss_room and not dungeon.navigation.boss_lock_triggered:
        lock_unvisited_rooms(dungeon)
        dungeon.navigation.boss_lock_triggered = True
        boss_lock = True

    auto_cleared = False
    if not room.beasts:
        auto_cleared = clear_room(dungeon, room_id).newly_cleared

    return TravelResult(
        previous_room_id=previous,
        current_room_id=room_id,
        first_visit=first_visit,
        auto_cleared=auto_cleared,
        boss_lock_triggered=boss_lock,
    )
