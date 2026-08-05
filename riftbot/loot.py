from __future__ import annotations

from dataclasses import dataclass

from .models import GeneratedDungeon, Relic


RELIC_VALUE_BY_RARITY: dict[str, int] = {
    "Common": 1,
    "Uncommon": 2,
    "Rare": 3,
    "Epic": 4,
    "Legendary": 5
}


@dataclass(frozen=True)
class ClearResult:
    room_id: int
    newly_cleared: bool
    dust_added: int = 0
    starmetal_added: int = 0
    relics_added: tuple[Relic, ...] = ()
    boss_cleared: bool = False


def clear_room(dungeon: GeneratedDungeon, room_id: int) -> ClearResult:
    progress = dungeon.navigation.room_progress[room_id]
    room = dungeon.rooms[room_id]

    if progress.cleared or room_id in dungeon.ledger.cleared_room_ids:
        return ClearResult(room_id=room_id, newly_cleared=False)
    if not progress.visited:
        raise ValueError("A room cannot be cleared before being visited.")

    dust = sum(beast.power_level for beast in room.beasts)
    starmetal = room.treasure.starmetal
    relics = tuple(room.treasure.relics)

    dungeon.ledger.dust += dust
    dungeon.ledger.starmetal += starmetal
    dungeon.ledger.relics.extend(relics)
    dungeon.ledger.cleared_room_ids.add(room_id)

    room.beasts.clear()
    room.treasure.starmetal = 0
    room.treasure.relics.clear()
    progress.cleared = True

    if room.is_boss_room:
        dungeon.ledger.revealed = True

    return ClearResult(
        room_id=room_id,
        newly_cleared=True,
        dust_added=dust,
        starmetal_added=starmetal,
        relics_added=relics,
        boss_cleared=room.is_boss_room,
    )


def render_ledger(dungeon: GeneratedDungeon) -> str:
    if not dungeon.ledger.revealed:
        return "The Rift Loot Ledger will be revealed when the Boss Room is cleared."

    lines = [
        "## Rift Loot Ledger",
        f"**Starmetal:** {dungeon.ledger.starmetal} SM",
        f"**Rift Dust:** {dungeon.ledger.dust} Dust",
        "",
        "**Relics**",
    ]
    if not dungeon.ledger.relics:
        lines.append("- None")
    else:
        for relic in dungeon.ledger.relics:
            lines.append(
                f"- **{relic.name}** — {relic.rarity}, Level {relic.level}, {RELIC_VALUE_BY_RARITY[relic.rarity] * relic.level} CE"
            )
    return "\n".join(lines)
