from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class CommandRegistration:
    name: str
    help_text: str
    is_admin: bool = False
    owner: str | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)
    usage: str = ""
    app: str | None = None
    category: str = "chat"
    parent: str | None = None
    display_name: str = ""
    public: bool = True
    hidden: bool = False
    permission: str = ""
    role: str = ""
    order: int = 0


class CommandRegistry:
    """Runtime registry for chat/slash commands."""

    def __init__(self):
        self._commands: dict[str, CommandRegistration] = {}

    def register(
        self,
        name: str,
        help_text: str,
        *,
        is_admin: bool = False,
        owner: str | None = None,
        aliases: list[str] | tuple[str, ...] | None = None,
        usage: str = "",
        app: str | None = None,
        category: str = "chat",
        parent: str | None = None,
        display_name: str = "",
        public: bool = True,
        hidden: bool = False,
        permission: str = "",
        role: str = "",
        order: int = 0,
    ) -> CommandRegistration:
        key = (name or "").strip().lower()
        if not key:
            raise ValueError("command name must not be empty")

        alias_list = tuple(a.strip().lower() for a in (aliases or []) if str(a).strip())
        registration = CommandRegistration(
            name=key,
            help_text=help_text,
            is_admin=bool(is_admin),
            owner=owner,
            aliases=alias_list,
            usage=usage,
            app=app,
            category=category,
            parent=parent,
            display_name=display_name,
            public=bool(public),
            hidden=bool(hidden),
            permission=permission,
            role=role,
            order=int(order or 0),
        )
        self._commands[key] = registration
        for alias in alias_list:
            self._commands[alias] = registration
        return registration

    def unregister(self, name: str) -> bool:
        key = (name or "").strip().lower()
        registration = self._commands.get(key)
        if registration is None:
            return False

        to_remove = [command_name for command_name, value in self._commands.items() if value is registration]
        for command_name in to_remove:
            self._commands.pop(command_name, None)
        return True

    def get(self, name: str) -> CommandRegistration | None:
        return self._commands.get((name or "").strip().lower())

    def has(self, name: str) -> bool:
        return (name or "").strip().lower() in self._commands

    def commands(self) -> dict[str, CommandRegistration]:
        result: dict[str, CommandRegistration] = {}
        for name, registration in self._commands.items():
            if registration.name == name:
                result[name] = registration
        return result

    def visible_commands(
        self,
        *,
        is_admin: bool | None = None,
        include_hidden: bool = False,
        category: str | None = None,
    ) -> dict[str, CommandRegistration]:
        result: dict[str, CommandRegistration] = {}
        for name, registration in self.commands().items():
            if is_admin is not None and registration.is_admin != is_admin:
                continue
            if not include_hidden and registration.hidden:
                continue
            if category is not None and registration.category != category:
                continue
            result[name] = registration
        return result

    def names(self) -> list[str]:
        return sorted(self.commands().keys())
