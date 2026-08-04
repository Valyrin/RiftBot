from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import GeneratedDungeon, GeneratedRoom


ROOM_STATE_SYMBOLS = {
    "current": "@",
    "cleared": "C",
    "visited": "V",
    "seen": "S",
    "locked": "X",
    "unknown": "?",
}


def get_room_map_symbol(
    dungeon: GeneratedDungeon,
    room_id: int,
    *,
    show_states: bool = True,
) -> str:
    """Return the short symbol displayed inside a room."""

    if room_id == dungeon.navigation.current_room_id:
        return "@"

    if room_id == dungeon.entrance_room_id:
        return "E"

    if room_id == dungeon.boss_room_id:
        return "B"

    if not show_states:
        return str(room_id)

    progress = dungeon.navigation.room_progress[room_id]

    if progress.locked:
        return "X"

    if progress.cleared:
        return "C"

    if progress.visited:
        return "V"

    if progress.seen:
        return "S"

    return "?"


def get_room_center(room: GeneratedRoom) -> tuple[int, int]:
    """Return the approximate center of a generated room."""

    center_x = room.x + room.definition.width // 2
    center_y = room.y + room.definition.height // 2

    return center_x, center_y


def draw_horizontal_connection(
    canvas: list[list[str]],
    x1: int,
    x2: int,
    y: int,
) -> None:
    """Draw a horizontal corridor between two points."""

    start, end = sorted((x1, x2))

    for x in range(start + 1, end):
        existing = canvas[y][x]

        if existing == " ":
            canvas[y][x] = "─"
        elif existing == "│":
            canvas[y][x] = "┼"


def draw_vertical_connection(
    canvas: list[list[str]],
    y1: int,
    y2: int,
    x: int,
) -> None:
    """Draw a vertical corridor between two points."""

    start, end = sorted((y1, y2))

    for y in range(start + 1, end):
        existing = canvas[y][x]

        if existing == " ":
            canvas[y][x] = "│"
        elif existing == "─":
            canvas[y][x] = "┼"


def draw_connection(
    canvas: list[list[str]],
    first: tuple[int, int],
    second: tuple[int, int],
) -> None:
    """Draw an L-shaped corridor between two room centers."""

    x1, y1 = first
    x2, y2 = second

    if x1 == x2:
        draw_vertical_connection(canvas, y1, y2, x1)
        return

    if y1 == y2:
        draw_horizontal_connection(canvas, x1, x2, y1)
        return

    # L-shaped connection:
    # horizontal from the first room, then vertical to the second.
    draw_horizontal_connection(canvas, x1, x2, y1)
    draw_vertical_connection(canvas, y1, y2, x2)

    corner = canvas[y1][x2]

    if corner == " ":
        canvas[y1][x2] = "┐" if y2 > y1 else "┘"
    elif corner in {"─", "│"}:
        canvas[y1][x2] = "┼"


def draw_room(
    canvas: list[list[str]],
    room: GeneratedRoom,
    *,
    offset_x: int,
    offset_y: int,
    label: str,
) -> None:
    """Draw one rectangular room onto the map canvas."""

    left = room.x + offset_x
    top = room.y + offset_y
    right = left + room.definition.width - 1
    bottom = top + room.definition.height - 1

    # Corners
    canvas[top][left] = "┌"
    canvas[top][right] = "┐"
    canvas[bottom][left] = "└"
    canvas[bottom][right] = "┘"

    # Horizontal walls
    for x in range(left + 1, right):
        canvas[top][x] = "─"
        canvas[bottom][x] = "─"

    # Vertical walls
    for y in range(top + 1, bottom):
        canvas[y][left] = "│"
        canvas[y][right] = "│"

    # Room label
    interior_width = max(0, room.definition.width - 2)

    if interior_width == 0:
        return

    shown_label = label[:interior_width]
    label_y = top + room.definition.height // 2
    label_x = left + 1 + max(
        0,
        (interior_width - len(shown_label)) // 2,
    )

    for index, character in enumerate(shown_label):
        if label_x + index < right:
            canvas[label_y][label_x + index] = character


def render_dungeon_map(
    dungeon: GeneratedDungeon,
    *,
    show_unknown_rooms: bool = True,
    show_states: bool = True,
    padding: int = 2,
) -> str:
    """Render a generated dungeon as an ASCII/Unicode map.

    Parameters
    ----------
    dungeon:
        The generated dungeon to display.

    show_unknown_rooms:
        When false, Unknown rooms are omitted from the player map.

    show_states:
        Show room-state symbols rather than only room IDs.

    padding:
        Empty space placed around the map.

    Returns
    -------
    str
        A printable Discord-compatible map.
    """

    visible_rooms: dict[int, GeneratedRoom] = {}

    for room_id, room in dungeon.rooms.items():
        progress = dungeon.navigation.room_progress[room_id]

        is_unknown = (
            not progress.seen
            and not progress.visited
            and not progress.cleared
            and not progress.locked
            and room_id != dungeon.navigation.current_room_id
        )

        if is_unknown and not show_unknown_rooms:
            continue

        visible_rooms[room_id] = room

    if not visible_rooms:
        return "(No visible rooms.)"

    min_x = min(room.x for room in visible_rooms.values())
    min_y = min(room.y for room in visible_rooms.values())

    max_x = max(
        room.x + room.definition.width - 1
        for room in visible_rooms.values()
    )

    max_y = max(
        room.y + room.definition.height - 1
        for room in visible_rooms.values()
    )

    width = max_x - min_x + 1 + padding * 2
    height = max_y - min_y + 1 + padding * 2

    offset_x = -min_x + padding
    offset_y = -min_y + padding

    canvas = [
        [" " for _ in range(width)]
        for _ in range(height)
    ]

    # Draw corridors first so room walls overwrite corridor lines.
    drawn_connections: set[tuple[int, int]] = set()

    for room_id, room in visible_rooms.items():
        for connected_id in room.connected_room_ids:
            if connected_id not in visible_rooms:
                continue

            connection_key = tuple(sorted((room_id, connected_id)))

            if connection_key in drawn_connections:
                continue

            drawn_connections.add(connection_key)

            first_center = get_room_center(room)
            second_center = get_room_center(
                visible_rooms[connected_id]
            )

            first_center = (
                first_center[0] + offset_x,
                first_center[1] + offset_y,
            )
            second_center = (
                second_center[0] + offset_x,
                second_center[1] + offset_y,
            )

            draw_connection(
                canvas,
                first_center,
                second_center,
            )

    # Draw rooms over the corridor lines.
    for room_id, room in visible_rooms.items():
        state_symbol = get_room_map_symbol(
            dungeon,
            room_id,
            show_states=show_states,
        )

        # Including the room number helps distinguish rooms that share
        # the same state.
        label = f"{state_symbol}{room_id}"

        draw_room(
            canvas,
            room,
            offset_x=offset_x,
            offset_y=offset_y,
            label=label,
        )

    lines = [
        "".join(row).rstrip()
        for row in canvas
    ]

    # Remove empty lines at the top and bottom.
    while lines and not lines[0].strip():
        lines.pop(0)

    while lines and not lines[-1].strip():
        lines.pop()

    return "\n".join(lines)


def print_dungeon_map(
    dungeon: GeneratedDungeon,
    *,
    show_unknown_rooms: bool = True,
    show_states: bool = True,
) -> None:
    """Print the generated dungeon map to the console."""

    print(
        render_dungeon_map(
            dungeon,
            show_unknown_rooms=show_unknown_rooms,
            show_states=show_states,
        )
    )