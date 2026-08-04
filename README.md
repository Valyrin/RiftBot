# Rift Bot Prototype

A testable Python prototype for the Discord RPG Rift system designed in this conversation.

## Included

- Daily Rift listing generation
- Configurable Rift level, motif, ownership, and company-owner tables
- Seven-day expiration for **Available** Rifts only
- Atomic claiming using SQLite
- Dungeon generation only after a successful claim
- Exit-queue room generation with a minimum-size failsafe
- Grid placement with overlap and accidental-adjacency prevention
- Room states: Unknown, Seen, Visited, Cleared, Current, Locked
- Direct navigation to Seen, Visited, or Cleared rooms
- Boss-entry locking of unvisited and uncleared rooms
- Beast generation filtered by Rift motif
- Treasure and Rift Loot Ledger
- Boss-room completion and Ledger reveal
- Discord.py integration scaffold
- Unit tests and a command-line demonstration

## Important data note

The linked Google Sheet's publicly visible portion was not sufficient to extract every
Pokédex and motif row. The package therefore includes replaceable JSON data files in
`data/`. Replace those samples with exports from the real workbook, keeping the same
field names.

## Requirements

Python 3.11 or newer is recommended.

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run the demonstration

```bash
python demo.py
```

This will:

1. Initialize a SQLite database.
2. Generate daily Rift listings.
3. Claim the first available Rift.
4. Generate its dungeon.
5. Enter and clear rooms.
6. Print the final Ledger after the Boss room is cleared.

## Run tests

```bash
pytest
```

## Discord setup

The package does not include a bot token. Copy `.env.example` to `.env`, supply a token,
then adapt `riftbot/discord_cog.py` to your existing bot's command tree and permissions.

The scaffold creates a thread after a claim has succeeded and dungeon generation has
completed.

## Data formats

### `data/motifs.json`

```json
{
  "motif_id": "volcanic",
  "name": "Volcanic",
  "description": "A heated volcanic Rift.",
  "allowed_types": ["fire", "rock", "ground"],
  "forbidden_types": [],
  "type_match_mode": "any",
  "paradox_rule": "allowed"
}
```

### `data/pokedex.json`

```json
{
  "species_id": "004",
  "name": "Charmander",
  "types": ["fire"],
  "is_paradox": false
}
```

### `data/rooms.json`

`outward_exits` means **new exits after entering the room**. The incoming connection is
not included.

```json
{
  "roll_min": 2,
  "roll_max": 5,
  "room_id": "dead_end",
  "name": "Dead End",
  "width": 3,
  "height": 3,
  "outward_exits": 0,
  "beast_budget": 0,
  "starmetal": 5,
  "relic_chance": 0.0,
  "boss": false
}
```

## Production notes

- The SQLite repository uses conditional status updates to prevent duplicate claims.
- A multi-process deployment should use PostgreSQL row locking or optimistic versioning.
- Discord persistent views should be registered on bot startup.
- Replace the demonstration scheduling loop with your existing scheduler or the supplied
  `DailyRiftScheduler` service.
