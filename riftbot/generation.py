from __future__ import annotations

import re
from collections import deque
from datetime import datetime, timedelta, timezone
from random import Random
from typing import Any, Iterable
from uuid import uuid4

from .models import (
    Beast,
    GeneratedDungeon,
    GeneratedRoom,
    NavigationState,
    OwnershipType,
    ParadoxRule,
    PokedexEntry,
    Relic,
    RiftListing,
    RiftLootLedger,
    RiftMotif,
    RiftOwnership,
    RoomDefinition,
    RoomProgress,
    RoomTreasure,
    TypeMatchMode,
)


# ---------------------------------------------------------------------------
# Rift tables
# ---------------------------------------------------------------------------

RIFT_LEVEL_BY_ROLL: dict[int, str] = {
    2: "SS",
    3: "S",
    4: "A",
    5: "B",
    6: "C",
    7: "D",
    8: "D",
    9: "D",
    10: "E",
    11: "E",
    12: "E",
    13: "E",
    **{roll: "F" for roll in range(14, 27)},
    27: "E",
    28: "E",
    29: "E",
    30: "D",
    31: "D",
    32: "D",
    33: "C",
    34: "C",
    35: "C",
    36: "B",
    37: "B",
    38: "A",
    39: "A",
    40: "S",
}

# Numeric value used by XdYxRL formulae and Relic levels.
RIFT_LEVEL_VALUES: dict[str, int] = {
    "F": 1,
    "E": 2,
    "D": 3,
    "C": 4,
    "B": 5,
    "A": 6,
    "S": 7,
    "SS": 8,
}

COMPANY_OWNER_BY_ROLL: dict[int, str] = {
    2: "Lionsoft Industries",
    3: "Platinum Threads",
    4: "Pink Ribbon Foods",
    5: "Jacobson Armaments",
    6: "Lightwood Foundation",
    7: "City News Network",
    8: "Scarlet Corporation",
}


# ---------------------------------------------------------------------------
# Dice parsing
# ---------------------------------------------------------------------------

_DICE_PATTERN = re.compile(
    r"^(?P<count>[1-9]\d*)d(?P<sides>[1-9]\d*)(?P<rift>xRL)?$",
    re.IGNORECASE,
)


class DiceFormulaError(ValueError):
    """Raised when room data contains an invalid dice formula."""


def roll_dice(rng: Random, count: int, sides: int) -> int:
    if count <= 0:
        raise ValueError("Dice count must be positive.")
    if sides <= 0:
        raise ValueError("Dice sides must be positive.")

    return sum(rng.randint(1, sides) for _ in range(count))


def evaluate_dice_formula(
    formula: str,
    *,
    rng: Random,
    rift_level_value: int | None = None,
    allow_rift_multiplier: bool = True,
) -> int:
    """Roll ``XdY`` or ``XdYxRL``.

    Examples:
        ``1d6`` with no Rift multiplier
        ``4d6xRL`` multiplied by the numeric Rift Level

    ``rift_level_value`` is required when ``xRL`` appears.
    """

    if not isinstance(formula, str):
        raise DiceFormulaError("Dice formula must be a string.")

    normalized = formula.replace(" ", "").upper()
    match = _DICE_PATTERN.fullmatch(normalized)

    if match is None:
        raise DiceFormulaError(
            f"Invalid dice formula {formula!r}; expected XdY or XdYxRL."
        )

    count = int(match.group("count"))
    sides = int(match.group("sides"))
    has_rift_multiplier = match.group("rift") is not None

    if has_rift_multiplier and not allow_rift_multiplier:
        raise DiceFormulaError(
            f"Rift multiplier is not allowed in formula {formula!r}."
        )

    result = roll_dice(rng, count, sides)

    if has_rift_multiplier:
        if rift_level_value is None:
            raise DiceFormulaError(
                f"Formula {formula!r} requires a numeric Rift Level."
            )
        if rift_level_value <= 0:
            raise DiceFormulaError("Numeric Rift Level must be positive.")

        result *= rift_level_value

    return result


def roll_beast_count(formula: str, *, rng: Random) -> int:
    """Roll a Beast-count formula, which must use plain ``XdY``."""

    return evaluate_dice_formula(
        formula,
        rng=rng,
        allow_rift_multiplier=False,
    )


def roll_starmetal(
    formula: str | None,
    *,
    rng: Random,
    rift_level_value: int,
) -> int:
    """Return zero for null, otherwise evaluate an ``XdYxRL`` formula."""

    if formula is None or 'None':
        return 0

    normalized = formula.replace(" ", "").upper()
    if not normalized.endswith("XRL"):
        raise DiceFormulaError(
            f"Starmetal formula {formula!r} must use XdYxRL."
        )

    return evaluate_dice_formula(
        formula,
        rng=rng,
        rift_level_value=rift_level_value,
        allow_rift_multiplier=True,
    )


# ---------------------------------------------------------------------------
# Daily Rift generation
# ---------------------------------------------------------------------------

def roll_company_owner(rng: Random) -> str:
    while True:
        roll = rng.randint(1, 8)
        if roll != 1:
            return COMPANY_OWNER_BY_ROLL[roll]


def _motif_for_roll(
    motifs: list[RiftMotif],
    motif_roll: int,
) -> RiftMotif:
    """Resolve a 2d8 result.

    If motifs expose ``roll_min`` and ``roll_max``, those ranges are used.
    Otherwise the list is treated as ordered for rolls 2 through 16.
    """

    for motif in motifs:
        roll_min = getattr(motif, "roll_min", None)
        roll_max = getattr(motif, "roll_max", None)

        if (
            isinstance(roll_min, int)
            and isinstance(roll_max, int)
            and roll_min <= motif_roll <= roll_max
        ):
            return motif

    index = motif_roll - 2
    if 0 <= index < len(motifs):
        return motifs[index]

    raise LookupError(
        f"No motif entry covers 2d8 roll {motif_roll}."
    )


def generate_daily_rifts(
    motifs: list[RiftMotif],
    *,
    now: datetime | None = None,
    seed: int | None = None,
    count: int | None = None,
) -> list[RiftListing]:
    if not motifs:
        raise ValueError("At least one motif is required.")

    generated_at = now or datetime.now(timezone.utc)
    actual_seed = (
        seed
        if seed is not None
        else int(generated_at.timestamp() * 1_000_000)
    )
    rng = Random(actual_seed)

    rift_count = count if count is not None else rng.randint(1, 8)
    if rift_count <= 0:
        raise ValueError("Rift count must be positive.")

    listings: list[RiftListing] = []

    for index in range(rift_count):
        level_roll = roll_dice(rng, 2, 20)
        motif_roll = roll_dice(rng, 2, 8)

        rift_level = RIFT_LEVEL_BY_ROLL[level_roll]
        motif = _motif_for_roll(motifs, motif_roll)

        ownership = (
            RiftOwnership(
                OwnershipType.COUNCIL_ASSIGNED,
                "Council",
            )
            if rift_level in {"S", "SS"}
            else RiftOwnership(OwnershipType.INDEPENDENT)
        )

        listings.append(
            RiftListing(
                rift_id=f"{generated_at.date().isoformat()}-{index + 1}",
                generated_at=generated_at,
                expires_at=generated_at + timedelta(days=7),
                level_roll=level_roll,
                rift_level=rift_level,
                motif_roll=motif_roll,
                motif=motif,
                ownership=ownership,
                seed=Random(f"{actual_seed}:{index}").getrandbits(63),
            )
        )

    # Company ownership is assigned only to non-S/SS Rifts, and at least
    # one eligible Rift remains Independent.
    eligible = [
        listing
        for listing in listings
        if listing.rift_level not in {"S", "SS"}
    ]
    rng.shuffle(eligible)

    purchase_count = min(
        rng.randint(1, 6),
        max(0, len(eligible) - 1),
    )

    for listing in eligible[:purchase_count]:
        listing.ownership = RiftOwnership(
            OwnershipType.COMPANY,
            roll_company_owner(rng),
        )

    return listings


# ---------------------------------------------------------------------------
# Room-data access
# ---------------------------------------------------------------------------

def _field(source: Any, name: str, default: Any = None) -> Any:
    """Read a field from either a dataclass/object or a JSON dictionary."""

    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def lookup_room(
    entries: Iterable[RoomDefinition | dict[str, Any]],
    roll: int,
) -> RoomDefinition | dict[str, Any]:
    for entry in entries:
        roll_min = int(_field(entry, "roll_min"))
        roll_max = int(_field(entry, "roll_max"))

        if roll_min <= roll <= roll_max:
            return entry

    raise LookupError(f"No room definition covers 2d20 roll {roll}.")


def _room_name(definition: RoomDefinition | dict[str, Any]) -> str:
    return str(
        _field(
            definition,
            "name",
            _field(definition, "layout", "Room"),
        )
    )


def _room_width(definition: RoomDefinition | dict[str, Any]) -> int:
    # The current rooms.json does not include physical dimensions, so
    # sensible defaults are selected by layout.
    explicit = _field(definition, "width")
    if explicit is not None:
        return int(explicit)

    layout = str(_field(definition, "layout", "")).casefold()
    if "large room" in layout:
        return 5
    if "hallway" in layout:
        return 3
    if "junction" in layout:
        return 4
    return 3


def _room_height(definition: RoomDefinition | dict[str, Any]) -> int:
    explicit = _field(definition, "height")
    if explicit is not None:
        return int(explicit)

    layout = str(_field(definition, "layout", "")).casefold()
    if "large room" in layout:
        return 5
    if "hallway" in layout:
        return 6
    if "junction" in layout:
        return 4
    return 3


def _outward_exits(definition: RoomDefinition | dict[str, Any]) -> int:
    return max(0, int(_field(definition, "outward_exits", 0)))


def _beast_specs(
    definition: RoomDefinition | dict[str, Any],
) -> list[dict[str, str]]:
    value = _field(definition, "beasts", [])
    if value is None:
        return []

    if not isinstance(value, list):
        raise ValueError(
            f"Room {_room_name(definition)!r} has invalid beasts data."
        )

    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Each beasts entry must be an object.")

        count = item.get("count")
        rank = item.get("rank")

        if not isinstance(count, str) or not count:
            raise ValueError("Beast entry requires a count formula.")
        if not isinstance(rank, str) or not rank:
            raise ValueError("Beast entry requires a rank.")

        result.append({"count": count, "rank": rank})

    return result


def _starmetal_formula(
    definition: RoomDefinition | dict[str, Any],
) -> str | None:
    value = _field(definition, "starmetal")

    if value is None:
        return None

    # Supports either the requested direct string format or the earlier
    # {"formula": "..."} representation.
    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        formula = value.get("formula")
        if formula is None:
            return None
        if isinstance(formula, str):
            return formula

    raise ValueError(
        f"Room {_room_name(definition)!r} has invalid starmetal data."
    )


def _treasure_specs(
    definition: RoomDefinition | dict[str, Any],
) -> list[dict[str, Any]]:
    value = _field(definition, "treasure", [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Room treasure must be a list.")
    return [dict(item) for item in value]


def _boss_guarded(
    definition: RoomDefinition | dict[str, Any],
) -> bool:
    return bool(_field(definition, "boss_guarded", False))


def _as_generated_definition(
    definition: RoomDefinition | dict[str, Any],
    *,
    boss: bool = False,
) -> RoomDefinition:
    """Normalize JSON room data into the project's RoomDefinition model.

    Numerical contents are generated separately and placed directly on the
    GeneratedRoom.
    """

    return RoomDefinition(
        room_id=str(_field(definition, "room_id", uuid4())),
        name=_room_name(definition),
        roll_min=int(_field(definition, "roll_min", 0)),
        roll_max=int(_field(definition, "roll_max", 0)),
        width=_room_width(definition),
        height=_room_height(definition),
        outward_exits=_outward_exits(definition),
        beast_budget=0,
        starmetal=0,
        relic=0.0,
        boss=boss,
    )


# ---------------------------------------------------------------------------
# Spatial layout
# ---------------------------------------------------------------------------

def _candidate_positions(
    parent: GeneratedRoom,
    definition: RoomDefinition,
) -> list[tuple[int, int]]:
    gap = 1

    return [
        (
            parent.x,
            parent.y - definition.height - gap,
        ),
        (
            parent.x + parent.definition.width + gap,
            parent.y,
        ),
        (
            parent.x,
            parent.y + parent.definition.height + gap,
        ),
        (
            parent.x - definition.width - gap,
            parent.y,
        ),
    ]


def _can_place(
    candidate: GeneratedRoom,
    occupied: dict[tuple[int, int], int],
    parent_room_id: int,
) -> bool:
    cells = candidate.occupied_cells

    if any(cell in occupied for cell in cells):
        return False

    # Prevent accidental contact with unrelated rooms.
    for x, y in cells:
        for neighbor in (
            (x + 1, y),
            (x - 1, y),
            (x, y + 1),
            (x, y - 1),
        ):
            existing_room_id = occupied.get(neighbor)

            if (
                existing_room_id is not None
                and existing_room_id != parent_room_id
            ):
                return False

    return True


def _fallback_position(
    definition: RoomDefinition,
    occupied: dict[tuple[int, int], int],
) -> tuple[int, int]:
    """Find a collision-free location to the east of the current layout."""

    max_x = max(x for x, _ in occupied)
    min_y = min(y for _, y in occupied)
    return max_x + 3, min_y


# ---------------------------------------------------------------------------
# Motif filtering and Beast generation
# ---------------------------------------------------------------------------

def _matches_motif(entry: PokedexEntry, motif: RiftMotif) -> bool:
    restrictions = motif.restrictions

    if entry.types & restrictions.forbidden_types:
        return False

    if (
        restrictions.paradox_rule is ParadoxRule.REQUIRED
        and not entry.is_paradox
    ):
        return False

    if (
        restrictions.paradox_rule is ParadoxRule.FORBIDDEN
        and entry.is_paradox
    ):
        return False

    allowed = restrictions.allowed_types

    if not allowed:
        return True

    if restrictions.type_match_mode is TypeMatchMode.ANY:
        return bool(entry.types & allowed)

    if restrictions.type_match_mode is TypeMatchMode.ALL:
        return allowed.issubset(entry.types)

    return entry.types == allowed


def eligible_species(
    pokedex: list[PokedexEntry],
    motif: RiftMotif,
) -> list[PokedexEntry]:
    result = [
        entry
        for entry in pokedex
        if _matches_motif(entry, motif)
    ]

    if not result:
        raise ValueError(
            f"No Pokédex entries satisfy motif {motif.name!r}."
        )

    return result


# These are defaults because the supplied room table defines Beast ranks,
# but does not define the exact Beast Level formula for each rank.
#
# Change this one mapping if your game uses different values.
BEAST_LEVEL_OFFSETS: dict[str, tuple[int, int]] = {
    "Low-Rank": (-1, 0),
    "Mid-Rank": (0, 1),
    "High-Rank": (1, 2),
    "Tree-Rank": (2, 3),
}


def roll_beast_level(
    rank: str,
    *,
    rift_level_value: int,
    rng: Random,
) -> int:
    try:
        minimum_offset, maximum_offset = BEAST_LEVEL_OFFSETS[rank]
    except KeyError as error:
        raise ValueError(f"Unknown Beast rank {rank!r}.") from error

    offset = rng.randint(minimum_offset, maximum_offset)
    return max(1, rift_level_value + offset)


def generate_beasts_from_specs(
    beast_specs: list[dict[str, str]],
    *,
    pokedex: list[PokedexEntry],
    motif: RiftMotif,
    rift_level_value: int,
    rng: Random,
) -> list[Beast]:
    if not beast_specs:
        return []

    candidates = eligible_species(pokedex, motif)
    beasts: list[Beast] = []

    for spec in beast_specs:
        count = roll_beast_count(spec["count"], rng=rng)
        rank = spec["rank"]

        for _ in range(count):
            species = rng.choice(candidates)

            beasts.append(
                Beast(
                    beast_id=str(uuid4()),
                    species_id=species.species_id,
                    species_name=species.name,
                    types=species.types,
                    is_paradox=species.is_paradox,
                    power_level=roll_beast_level(
                        rank,
                        rift_level_value=rift_level_value,
                        rng=rng,
                    ),
                )
            )

    return beasts


# ---------------------------------------------------------------------------
# Treasure generation
# ---------------------------------------------------------------------------

def _relic_from_spec(
    spec: dict[str, Any],
    *,
    motif: RiftMotif,
    rift_level_value: int,
) -> list[Relic]:
    quantity = max(1, int(spec.get("quantity", 1)))
    kind = str(spec.get("kind", "")).casefold()

    if kind == "chest":
        rarity = str(spec.get("rarity", "Common"))
        name = f"{motif.name} Relic"
    elif kind == "rift_item":
        rarity = "Rift Item"
        name = f"{motif.name} Rift Item"
    elif kind == "legendary_level_loot":
        rarity = "Legendary"
        name = f"Legendary {motif.name} Relic"
    else:
        return []

    return [
        Relic(
            relic_id=str(uuid4()),
            name=name,
            rarity=rarity,
            level=rift_level_value,
        )
        for _ in range(quantity)
    ]


def generate_room_treasure(
    definition: RoomDefinition | dict[str, Any],
    *,
    motif: RiftMotif,
    rift_level_value: int,
    rng: Random,
) -> RoomTreasure:
    starmetal = roll_starmetal(
        _starmetal_formula(definition),
        rng=rng,
        rift_level_value=rift_level_value,
    )

    relics: list[Relic] = []
    for spec in _treasure_specs(definition):
        relics.extend(
            _relic_from_spec(
                spec,
                motif=motif,
                rift_level_value=rift_level_value,
            )
        )

    return RoomTreasure(
        starmetal=starmetal,
        relics=relics,
    )


# ---------------------------------------------------------------------------
# Dungeon generation
# ---------------------------------------------------------------------------

def generate_dungeon(
    rift: RiftListing,
    room_entries: list[RoomDefinition | dict[str, Any]],
    pokedex: list[PokedexEntry],
    *,
    minimum_rooms: int = 3,
    maximum_rooms: int = 10000,
) -> GeneratedDungeon:
    """Generate a claimed Rift's dungeon.

    Room content format:
        starmetal: null or "XdYxRL"
        beasts:
          - count: "XdY"
            rank: "Low-Rank" | "Mid-Rank" | "High-Rank" | "Tree-Rank"
    """

    if minimum_rooms < 2:
        raise ValueError("minimum_rooms must be at least 2.")
    if maximum_rooms < minimum_rooms:
        raise ValueError(
            "maximum_rooms cannot be lower than minimum_rooms."
        )

    rng = Random(f"{rift.seed}:dungeon")
    rift_level_value = RIFT_LEVEL_VALUES[rift.rift_level]

    entrance_definition = RoomDefinition(
        room_id="entrance",
        name="Rift Entrance",
        roll_min=0,
        roll_max=0,
        width=3,
        height=3,
        outward_exits=1,
        beast_budget=0,
        starmetal=0,
        relic=0.0,
        boss=False,
    )

    entrance = GeneratedRoom(
        instance_id=0,
        definition=entrance_definition,
        x=0,
        y=0,
        parent_room_id=None,
        depth=0,
    )

    rooms: dict[int, GeneratedRoom] = {0: entrance}
    source_definitions: dict[int, RoomDefinition | dict[str, Any]] = {
        0: entrance_definition
    }
    occupied = {
        cell: entrance.instance_id
        for cell in entrance.occupied_cells
    }

    # Each queue entry represents one unspent outward exit.
    pending_exits: deque[int] = deque([entrance.instance_id])

    while len(rooms) < maximum_rooms:
        if not pending_exits:
            if len(rooms) >= minimum_rooms:
                break

            # Minimum-size failsafe: add one exit to the latest room.
            pending_exits.append(max(rooms))

        parent_id = pending_exits.popleft()
        parent = rooms[parent_id]

        raw_definition = lookup_room(
            room_entries,
            roll_dice(rng, 2, 20),
        )
        generated_definition = _as_generated_definition(
            raw_definition
        )

        positions = _candidate_positions(
            parent,
            generated_definition,
        )
        rng.shuffle(positions)

        placed: GeneratedRoom | None = None

        for x, y in positions:
            candidate = GeneratedRoom(
                instance_id=len(rooms),
                definition=generated_definition,
                x=x,
                y=y,
                parent_room_id=parent_id,
                depth=parent.depth + 1,
            )

            if _can_place(candidate, occupied, parent_id):
                placed = candidate
                break

        if placed is None:
            x, y = _fallback_position(
                generated_definition,
                occupied,
            )
            placed = GeneratedRoom(
                instance_id=len(rooms),
                definition=generated_definition,
                x=x,
                y=y,
                parent_room_id=parent_id,
                depth=parent.depth + 1,
            )

            if not _can_place(placed, occupied, parent_id):
                raise RuntimeError(
                    "Unable to find a valid fallback room position."
                )

        rooms[placed.instance_id] = placed
        source_definitions[placed.instance_id] = raw_definition

        parent.connected_room_ids.append(placed.instance_id)
        placed.connected_room_ids.append(parent_id)

        for cell in placed.occupied_cells:
            occupied[cell] = placed.instance_id

        for _ in range(_outward_exits(raw_definition)):
            pending_exits.append(placed.instance_id)

    # The deepest generated room is the Boss Room.
    boss_room_id = max(
        rooms,
        key=lambda room_id: (
            rooms[room_id].depth,
            room_id,
        ),
    )
    boss_room = rooms[boss_room_id]
    boss_room.definition = RoomDefinition(
        room_id=boss_room.definition.room_id,
        name=f"Boss: {boss_room.definition.name}",
        roll_min=boss_room.definition.roll_min,
        roll_max=boss_room.definition.roll_max,
        width=boss_room.definition.width,
        height=boss_room.definition.height,
        outward_exits=0,
        beast_budget=0,
        starmetal=0,
        relic=0.0,
        boss=True,
    )

    # Populate contents only after layout succeeds.
    for room_id, room in rooms.items():
        if room_id == entrance.instance_id:
            room.beasts = []
            room.treasure = RoomTreasure()
            continue

        raw_definition = source_definitions[room_id]
        beast_specs = _beast_specs(raw_definition)

        room.beasts = generate_beasts_from_specs(
            beast_specs,
            pokedex=pokedex,
            motif=rift.motif,
            rift_level_value=rift_level_value,
            rng=rng,
        )

        # A Legendary Chest Guarded by Boss needs an actual guardian.
        if _boss_guarded(raw_definition) and not room.beasts:
            species = rng.choice(
                eligible_species(pokedex, rift.motif)
            )
            room.beasts.append(
                Beast(
                    beast_id=str(uuid4()),
                    species_id=species.species_id,
                    species_name=species.name,
                    types=species.types,
                    is_paradox=species.is_paradox,
                    power_level=max(
                        1,
                        rift_level_value + 3,
                    ),
                )
            )
        print(raw_definition)
        room.treasure = generate_room_treasure(
            raw_definition,
            motif=rift.motif,
            rift_level_value=rift_level_value,
            rng=rng,
        )

    progress = {
        room_id: RoomProgress(room_id=room_id)
        for room_id in rooms
    }

    progress[entrance.instance_id].seen = True
    progress[entrance.instance_id].visited = True

    for adjacent_id in entrance.connected_room_ids:
        progress[adjacent_id].seen = True

    return GeneratedDungeon(
        dungeon_id=str(uuid4()),
        rift_id=rift.rift_id,
        rooms=rooms,
        entrance_room_id=entrance.instance_id,
        boss_room_id=boss_room_id,
        navigation=NavigationState(
            current_room_id=entrance.instance_id,
            room_progress=progress,
        ),
        ledger=RiftLootLedger(),
    )