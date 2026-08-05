from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class RiftStatus(StrEnum):
    AVAILABLE = "available"
    GENERATING = "generating"
    READY = "ready"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class OwnershipType(StrEnum):
    INDEPENDENT = "independent"
    COMPANY = "company"
    COUNCIL_ASSIGNED = "council_assigned"
    REGIONAL = "regional"


class RoomState(StrEnum):
    UNKNOWN = "unknown"
    SEEN = "seen"
    VISITED = "visited"
    CLEARED = "cleared"
    CURRENT = "current"
    LOCKED = "locked"


class PokemonType(StrEnum):
    NORMAL = "normal"
    FIRE = "fire"
    WATER = "water"
    ELECTRIC = "electric"
    GRASS = "grass"
    ICE = "ice"
    FIGHTING = "fighting"
    POISON = "poison"
    GROUND = "ground"
    FLYING = "flying"
    PSYCHIC = "psychic"
    BUG = "bug"
    ROCK = "rock"
    GHOST = "ghost"
    DRAGON = "dragon"
    DARK = "dark"
    STEEL = "steel"
    FAIRY = "fairy"


class TypeMatchMode(StrEnum):
    ANY = "any"
    ALL = "all"
    EXACT = "exact"


class ParadoxRule(StrEnum):
    ALLOWED = "allowed"
    FORBIDDEN = "forbidden"
    REQUIRED = "required"


@dataclass(frozen=True, slots=True)
class RiftOwnership:
    ownership_type: OwnershipType
    owner_name: str | None = None


@dataclass(frozen=True, slots=True)
class BeastRestrictions:
    allowed_types: frozenset[PokemonType] = frozenset()
    forbidden_types: frozenset[PokemonType] = frozenset()
    type_match_mode: TypeMatchMode = TypeMatchMode.ANY
    paradox_rule: ParadoxRule = ParadoxRule.ALLOWED


@dataclass(frozen=True, slots=True)
class RiftMotif:
    motif_id: str
    name: str
    description: str
    restrictions: BeastRestrictions


@dataclass(frozen=True, slots=True)
class PokedexEntry:
    species_id: str
    name: str
    types: frozenset[PokemonType]
    is_paradox: bool


@dataclass(frozen=True, slots=True)
class Beast:
    beast_id: str
    species_id: str
    species_name: str
    types: frozenset[PokemonType]
    is_paradox: bool
    power_level: int


@dataclass(frozen=True, slots=True)
class Relic:
    relic_id: str
    name: str
    rarity: str
    level: int
    creation_energy: int


@dataclass(slots=True)
class RoomTreasure:
    starmetal: int = 0
    relics: list[Relic] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RoomDefinition:
    room_id: str
    name: str
    roll_min: int
    roll_max: int
    width: int
    height: int
    outward_exits: int
    beast_budget: int
    starmetal: str | None
    relic: float
    boss: bool = False
    beasts: tuple[dict[str, str], ...] = ()
    treasure: tuple[dict[str, Any], ...] = ()
    boss_guarded: bool = False


@dataclass(slots=True)
class GeneratedRoom:
    instance_id: int
    definition: RoomDefinition
    x: int
    y: int
    parent_room_id: int | None
    depth: int
    connected_room_ids: list[int] = field(default_factory=list)
    beasts: list[Beast] = field(default_factory=list)
    treasure: RoomTreasure = field(default_factory=RoomTreasure)

    @property
    def is_boss_room(self) -> bool:
        return self.definition.boss

    @property
    def occupied_cells(self) -> set[tuple[int, int]]:
        return {
            (self.x + dx, self.y + dy)
            for dx in range(self.definition.width)
            for dy in range(self.definition.height)
        }


@dataclass(slots=True)
class RoomProgress:
    room_id: int
    seen: bool = False
    visited: bool = False
    cleared: bool = False
    locked: bool = False


@dataclass(slots=True)
class NavigationState:
    current_room_id: int
    room_progress: dict[int, RoomProgress]
    boss_lock_triggered: bool = False


@dataclass(slots=True)
class RiftLootLedger:
    dust: int = 0
    starmetal: int = 0
    relics: list[Relic] = field(default_factory=list)
    cleared_room_ids: set[int] = field(default_factory=set)
    revealed: bool = False


@dataclass(slots=True)
class GeneratedDungeon:
    dungeon_id: str
    rift_id: str
    rooms: dict[int, GeneratedRoom]
    entrance_room_id: int
    boss_room_id: int
    navigation: NavigationState
    ledger: RiftLootLedger


@dataclass(slots=True)
class RiftListing:
    rift_id: str
    generated_at: datetime
    expires_at: datetime
    level_roll: int
    rift_level: str
    motif_roll: int
    motif: RiftMotif
    ownership: RiftOwnership
    seed: int
    status: RiftStatus = RiftStatus.AVAILABLE
    claimed_by_user_id: int | None = None
    claimed_at: datetime | None = None
    dungeon_id: str | None = None
    thread_id: int | None = None

    @property
    def owner_display(self) -> str:
        if self.ownership.ownership_type is OwnershipType.COMPANY:
            return self.ownership.owner_name or "Unknown Company"
        if self.ownership.ownership_type is OwnershipType.COUNCIL_ASSIGNED:
            return "Council Assigned"
        if self.ownership.ownership_type is OwnershipType.REGIONAL:
            return self.ownership.owner_name or "Unknown Region"
        return "Independent"
