from datetime import datetime, timedelta, timezone
from pathlib import Path

from riftbot.data import load_motifs, load_pokedex, load_rooms
from riftbot.generation import generate_daily_rifts, generate_dungeon
from riftbot.loot import clear_room
from riftbot.models import RiftStatus, RoomState
from riftbot.navigation import room_state, travel_to_room
from riftbot.repository import RiftRepository


BASE = Path(__file__).parents[1]


def data():
    return (
        load_motifs(BASE / "data" / "motifs.json"),
        load_pokedex(BASE / "data" / "pokedex.json"),
        load_rooms(BASE / "data" / "rooms.json"),
    )


def test_available_only_expiration(tmp_path):
    motifs, _, _ = data()
    now = datetime.now(timezone.utc)
    rifts = generate_daily_rifts(motifs, now=now, seed=1, count=2)

    repository = RiftRepository(tmp_path / "test.sqlite3")
    for rift in rifts:
        rift.expires_at = now - timedelta(seconds=1)
        repository.save_rift(rift)

    assert repository.claim_available(rifts[1].rift_id, 42)
    expired = repository.expire_available(now)

    assert rifts[0].rift_id in expired
    assert rifts[1].rift_id not in expired
    assert repository.get_rift(rifts[0].rift_id).status is RiftStatus.EXPIRED
    assert repository.get_rift(rifts[1].rift_id).status is RiftStatus.GENERATING


def test_dungeon_generation_and_room_states():
    motifs, pokedex, rooms = data()
    rift = generate_daily_rifts(motifs, seed=2, count=1)[0]
    dungeon = generate_dungeon(
        rift, rooms, pokedex, minimum_rooms=6, maximum_rooms=30
    )

    assert len(dungeon.rooms) >= 6
    assert room_state(dungeon, dungeon.entrance_room_id) is RoomState.CURRENT
    assert any(
        room_state(dungeon, room_id) is RoomState.SEEN
        for room_id in dungeon.rooms
    )


def test_beast_free_room_auto_clears():
    motifs, pokedex, rooms = data()
    rift = generate_daily_rifts(motifs, seed=3, count=1)[0]
    dungeon = generate_dungeon(rift, rooms, pokedex)

    seen_ids = [
        room_id for room_id in dungeon.rooms
        if room_state(dungeon, room_id) is RoomState.SEEN
    ]
    assert seen_ids

    target = seen_ids[0]
    dungeon.rooms[target].beasts.clear()
    travel_to_room(dungeon, target)
    assert dungeon.navigation.room_progress[target].cleared


def test_clear_room_transfers_all_rewards():
    motifs, pokedex, rooms = data()
    rift = generate_daily_rifts(motifs, seed=4, count=1)[0]
    dungeon = generate_dungeon(rift, rooms, pokedex)

    target = next(
        room_id for room_id in dungeon.rooms
        if room_state(dungeon, room_id) is RoomState.SEEN
    )
    travel_to_room(dungeon, target)

    room = dungeon.rooms[target]
    expected_dust = sum(beast.power_level for beast in room.beasts)
    expected_sm = room.treasure.starmetal
    result = clear_room(dungeon, target)

    assert result.dust_added == expected_dust
    assert result.starmetal_added == expected_sm
    assert not room.beasts
    assert room.treasure.starmetal == 0
    assert target in dungeon.ledger.cleared_room_ids
