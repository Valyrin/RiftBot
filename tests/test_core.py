from datetime import datetime, timedelta, timezone
from pathlib import Path

from riftbot.data import load_motifs, load_pokedex, load_rooms
from riftbot.display import render_clear_result, render_travel_result
from random import Random

from riftbot.generation import (
    NON_BOSS_RELIC_RARITY_WEIGHTS,
    RELIC_RARITY_LEVELS,
    RIFT_LEVEL_VALUES,
    generate_daily_rifts,
    generate_dungeon,
    roll_starmetal,
    roll_regional_rift_counts,
)
from riftbot.loot import clear_room
from riftbot.models import OwnershipType, RiftStatus, RoomState
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


def test_regional_rift_counts_roll_independently_from_zero_to_three():
    counts = roll_regional_rift_counts(Random(7))
    values = list(counts.values())

    assert len(values) == 5
    assert all(0 <= value <= 3 for value in values)
    assert len(set(values)) > 1


def test_regional_rifts_are_added_after_standard_rifts():
    motifs, _, _ = data()
    standard_count = 2
    rifts = generate_daily_rifts(motifs, seed=8, count=standard_count)
    regional = rifts[standard_count:]

    assert regional
    assert all(
        rift.ownership.ownership_type is OwnershipType.REGIONAL
        for rift in regional
    )
    assert all(
        rift.ownership.owner_name in {
            "Moon Hammer", "Lightclaw", "Hoenn", "Alola", "Horona"
        }
        for rift in regional
    )
    assert all(
        rift.ownership.ownership_type is not OwnershipType.REGIONAL
        for rift in rifts[:standard_count]
    )


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


def test_room_loader_preserves_generated_content_specs():
    _, _, rooms = data()

    beast_room = next(room for room in rooms if room.beasts)
    starmetal_room = next(room for room in rooms if room.starmetal)

    assert beast_room.beasts[0]["count"]
    assert beast_room.beasts[0]["rank"]
    assert starmetal_room.starmetal.endswith("xRL")


def test_starmetal_formula_is_rolled_and_null_is_zero():
    assert roll_starmetal(
        "1d1xRL", rng=Random(1), rift_level_value=4
    ) == 4
    assert roll_starmetal(
        None, rng=Random(1), rift_level_value=4
    ) == 0


def test_boss_has_legendary_relic_with_creation_energy():
    motifs, pokedex, rooms = data()
    rift = generate_daily_rifts(motifs, seed=5, count=1)[0]
    dungeon = generate_dungeon(rift, rooms, pokedex)

    boss_relics = dungeon.rooms[dungeon.boss_room_id].treasure.relics
    legendary = next(
        relic for relic in boss_relics if relic.rarity == "Legendary"
    )
    rift_level = RIFT_LEVEL_VALUES[rift.rift_level]

    assert legendary.level == rift_level
    assert legendary.creation_energy == (
        rift_level * RELIC_RARITY_LEVELS["Legendary"]
    )


def test_all_generated_relics_use_canonical_rarities_and_energy():
    motifs, pokedex, rooms = data()
    for seed in range(1, 11):
        rift = generate_daily_rifts(motifs, seed=seed, count=1)[0]
        dungeon = generate_dungeon(
            rift, rooms, pokedex, minimum_rooms=10, maximum_rooms=30
        )
        for room in dungeon.rooms.values():
            for relic in room.treasure.relics:
                assert relic.rarity in RELIC_RARITY_LEVELS
                assert relic.name.endswith(" Relic")
                assert "Rift Item" not in relic.name
                if room.is_boss_room:
                    assert relic.rarity == "Legendary"
                else:
                    assert relic.rarity in NON_BOSS_RELIC_RARITY_WEIGHTS
                assert relic.level == RIFT_LEVEL_VALUES[rift.rift_level]
                assert relic.creation_energy == (
                    relic.level * RELIC_RARITY_LEVELS[relic.rarity]
                )


def test_non_boss_rarity_weights_favor_lower_tiers():
    weights = NON_BOSS_RELIC_RARITY_WEIGHTS
    assert weights["Common"] > weights["Uncommon"]
    assert weights["Uncommon"] > weights["Rare"]
    assert weights["Rare"] > weights["Epic"]
    assert "Legendary" not in weights


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
    dungeon.rooms[target].treasure.starmetal = 12
    result = travel_to_room(dungeon, target)
    assert dungeon.navigation.room_progress[target].cleared
    assert result.auto_cleared
    assert result.starmetal_acquired == 12
    assert dungeon.ledger.starmetal == 12
    assert render_travel_result(result) == (
        f"Travelled to room {target}.\nCleared room {target}: +12 SM."
    )


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
    assert render_clear_result(result) == (
        f"Cleared room {target}: +{expected_dust} Dust, "
        f"+{expected_sm} SM."
    )
    assert not room.beasts
    assert room.treasure.starmetal == 0
    assert target in dungeon.ledger.cleared_room_ids
