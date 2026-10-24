# Help

## Purpose

Shows command help using the controller's registered command catalogue.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/help` | Show command help. | Everyone |
| `/helpall` | Show the expanded command listing. | Everyone |

Administrative help is provided separately by Admin through `//help` and
`//helpall`. Individual apps may also offer their own detailed help commands.

## Configuration

No app-specific `app_defaults.toml`. Available commands depend on the loadout and
registered metadata; command handlers remain responsible for access checks.

## Changes And Limits

Lists commands from the active loadout. Administrative help and app management
are provided by Admin.

## Credits

XAseco command help: Xymph (updates).
PyXaseco adaptation: Nila / PyXaseco project.
