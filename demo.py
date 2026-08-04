from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from riftbot.data import load_motifs, load_pokedex, load_rooms
from riftbot.generation import generate_daily_rifts
from riftbot.loot import clear_room, render_ledger
from riftbot.navigation import room_state, travel_to_room
from riftbot.repository import RiftRepository
from riftbot.service import RiftService
from riftbot.display import print_dungeon_map

import random


BASE = Path(__file__).parent


def main() -> None:
    motifs = load_motifs(BASE / "data" / "motifs.json")
    pokedex = load_pokedex(BASE / "data" / "pokedex.json")
    rooms = load_rooms(BASE / "data" / "rooms.json")

    db_path = BASE / "demo.sqlite3"
    if db_path.exists():
        db_path.unlink()

    repository = RiftRepository(db_path)
    listings = generate_daily_rifts(
        motifs,
        now=datetime.now(timezone.utc),
        seed=random.randint(1,10000),
        count=3,
    )
    for listing in listings:
        repository.save_rift(listing)

    print("Generated Rifts:")
    for listing in listings:
        print(
            f"- {listing.rift_id}: {listing.rift_level} "
            f"{listing.motif.name}, {listing.owner_display}"
        )

    target = listings[0]
    service = RiftService(repository, rooms, pokedex)
    rift, dungeon = service.claim_and_generate(target.rift_id, user_id=1001)

    print(f"\nClaimed {rift.rift_id}; generated {len(dungeon.rooms)} rooms.")
    print("Room states:")
    for room_id in dungeon.rooms:
        print(f"- Room {room_id}: {room_state(dungeon, room_id).value}")
    
    print_dungeon_map(dungeon)

    # Demonstration exploration: repeatedly choose a Seen room and clear it.
    safety = 0
    while not dungeon.ledger.revealed and safety < 200:
        safety += 1
        seen = [
            room_id
            for room_id in dungeon.rooms
            if room_state(dungeon, room_id).value == "seen"
        ]
        if not seen:
            # Clear current combat room if necessary.
            current = dungeon.navigation.current_room_id
            if dungeon.rooms[current].beasts:
                result = clear_room(dungeon, current)
                print(
                    f"Cleared room {current}: +{result.dust_added} Dust, "
                    f"+{result.starmetal_added} SM."
                )
            else:
                break
            continue

        destination = seen[0]
        result = travel_to_room(dungeon, destination)
        print(f"Travelled to room {destination}.")
        if dungeon.rooms[destination].beasts:
            clear_result = clear_room(dungeon, destination)
            print(
                f"Cleared room {destination}: +{clear_result.dust_added} Dust, "
                f"+{clear_result.starmetal_added} SM."
            )

        if destination == dungeon.boss_room_id:
            break

    if not dungeon.ledger.revealed:
        # Direct demonstration fallback: visit/clear path to boss if it remains reachable.
        boss_id = dungeon.boss_room_id
        progress = dungeon.navigation.room_progress[boss_id]
        if not progress.locked:
            progress.seen = True
            travel_to_room(dungeon, boss_id)
            if dungeon.rooms[boss_id].beasts:
                clear_room(dungeon, boss_id)

    if dungeon.ledger.revealed:
        service.complete_rift(rift)
        print("\n" + render_ledger(dungeon))
    else:
        print("\nBoss room was locked before the demonstration reached it.")


if __name__ == "__main__":
    main()
