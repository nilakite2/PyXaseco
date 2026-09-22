from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from pyxaseco.core.command_registry import CommandRegistration

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player


def command_sort_key(item: tuple[str, CommandRegistration]) -> tuple[str, str, int, str]:
    name, registration = item
    return (
        str(registration.app or ""),
        str(registration.category or ""),
        int(registration.order or 0),
        str(registration.display_name or name),
    )


def command_label(registration: CommandRegistration, *, prefix_slash: bool = True) -> str:
    usage = str(getattr(registration, "usage", "") or "").strip()
    if usage:
        return usage

    display_name = str(getattr(registration, "display_name", "") or registration.name).strip()
    if prefix_slash and not display_name.startswith("/"):
        return f"/{display_name}"
    return display_name


def iter_commands(
    aseco: "Aseco",
    *,
    is_admin: bool | None = None,
    include_hidden: bool = False,
    category: str | None = None,
    app: str | None = None,
) -> list[tuple[str, CommandRegistration]]:
    items: list[tuple[str, CommandRegistration]] = []
    for name, registration in aseco.iter_registered_commands():
        if is_admin is not None and registration.is_admin != is_admin:
            continue
        if not include_hidden and registration.hidden:
            continue
        if category is not None and registration.category != category:
            continue
        if app is not None and registration.app != app:
            continue
        items.append((name, registration))
    items.sort(key=command_sort_key)
    return items


def visible_chat_commands_for_player(
    aseco: "Aseco",
    player: "Player",
) -> list[tuple[str, CommandRegistration]]:
    result: list[tuple[str, CommandRegistration]] = []
    for name, registration in iter_commands(aseco, is_admin=False):
        try:
            if not aseco.allow_ability(player, name.split("/")[0]):
                continue
        except Exception:
            pass
        result.append((name, registration))
    return result


def visible_admin_commands_for_player(
    aseco: "Aseco",
    player: "Player",
    *,
    categories: tuple[str, ...] | None = None,
    auth_check: Callable[[str, CommandRegistration], bool] | None = None,
) -> list[tuple[str, CommandRegistration]]:
    result: list[tuple[str, CommandRegistration]] = []
    seen: set[str] = set()

    for name, registration in iter_commands(aseco, is_admin=True):
        reg_category = str(getattr(registration, "category", "") or "")
        if categories is None:
            if not reg_category.startswith("admin-"):
                continue
        elif reg_category not in categories:
            continue

        key = (
            getattr(registration, "permission", "")
            or getattr(registration, "display_name", "")
            or name.split("/")[-1]
        ).strip().lower()
        if not key or key in seen:
            continue
        if auth_check is not None and not auth_check(key, registration):
            continue
        result.append((name, registration))
        seen.add(key)

    return result


def combined_visible_commands_for_player(
    aseco: "Aseco",
    player: "Player",
    *,
    admin_auth_check: Callable[[str, CommandRegistration], bool] | None = None,
) -> list[tuple[str, CommandRegistration]]:
    rows: list[tuple[str, CommandRegistration]] = []
    seen: set[str] = set()

    for name, registration in visible_chat_commands_for_player(aseco, player):
        key = name.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append((name, registration))

    for name, registration in visible_admin_commands_for_player(
        aseco,
        player,
        auth_check=admin_auth_check,
    ):
        key = name.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append((name, registration))

    rows.sort(key=command_sort_key)
    return rows


def admin_ability_names(
    aseco: "Aseco",
    *,
    categories: tuple[str, ...] | None = None,
    legacy_names: set[str] | None = None,
) -> list[str]:
    names = set(legacy_names or set())
    for name, registration in iter_commands(aseco, is_admin=True):
        reg_category = str(getattr(registration, "category", "") or "")
        if categories is None:
            if not reg_category.startswith("admin-"):
                continue
        elif reg_category not in categories:
            continue

        part = (
            getattr(registration, "permission", "")
            or getattr(registration, "display_name", "")
            or str(name).split("/")[-1]
        ).strip().lower()
        if part:
            names.add(part)
    return sorted(names)
