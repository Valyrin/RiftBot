from __future__ import annotations

import json
from pathlib import Path

from .models import (
    BeastRestrictions,
    ParadoxRule,
    PokedexEntry,
    PokemonType,
    RiftMotif,
    RoomDefinition,
    TypeMatchMode,
)


def _load_json(path: str | Path) -> list[dict]:
    with Path(path).open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, list):
        raise ValueError(f"{path} must contain a JSON list.")
    return value


def load_motifs(path: str | Path) -> list[RiftMotif]:
    result = []
    for row in _load_json(path):
        result.append(
            RiftMotif(
                motif_id=str(row["motif_id"]),
                name=str(row["name"]),
                description=str(row.get("description", "")),
                restrictions=BeastRestrictions(
                    allowed_types=frozenset(
                        PokemonType(value.lower())
                        for value in row.get("allowed_types", [])
                    ),
                    forbidden_types=frozenset(
                        PokemonType(value.lower())
                        for value in row.get("forbidden_types", [])
                    ),
                    type_match_mode=TypeMatchMode(
                        row.get("type_match_mode", "any")
                    ),
                    paradox_rule=ParadoxRule(
                        row.get("paradox_rule", "allowed")
                    ),
                ),
            )
        )
    return result


def load_pokedex(path: str | Path) -> list[PokedexEntry]:
    result = []
    for row in _load_json(path):
        result.append(
            PokedexEntry(
                species_id=str(row["species_id"]),
                name=str(row["name"]),
                types=frozenset(
                    PokemonType(value.lower())
                    for value in row["types"]
                ),
                is_paradox=bool(row.get("is_paradox", False)),
            )
        )
    return result


def load_rooms(path: str | Path) -> list[RoomDefinition]:
    return [
        RoomDefinition(
            room_id=str(row["room_id"]),
            name=str(row["name"]),
            roll_min=int(row["roll_min"]),
            roll_max=int(row["roll_max"]),
            width=int(row.get("width", 3)),
            height=int(row.get("height", 3)),
            outward_exits=int(row["outward_exits"]),
            beast_budget=int(row.get("beast_budget", 0)),
            starmetal=row.get("starmetal"),
            relic=float(row.get("relic", 0)),
            boss=bool(row.get("boss", False)),
            beasts=tuple(dict(spec) for spec in row.get("beasts", [])),
            treasure=tuple(
                dict(spec) for spec in row.get("treasure", [])
            ),
            boss_guarded=bool(row.get("boss_guarded", False)),
        )
        for row in _load_json(path)
    ]
