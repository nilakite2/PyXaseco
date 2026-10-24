# Server Admin Bridge

## Purpose

On controller sync, grants the dedicated server's own login MasterAdmin status in memory, so
administrative chat commands sent under that login can be authorized.

Normal in-game administration does not require this app. It is also separate from
the [Local Management Bridge](../management_bridge/README.md) used by the
PyXaseco Administrator Console; neither bridge enables the other.

## Commands

No new chat commands. The app authorizes existing Admin commands rather than
adding its own command interface or injecting a synthetic player.

## Configuration

Disabled in the shipped loadout. Enable `app/server_admin_bridge` in `apps.toml`
or run `//apps enable server_admin_bridge`, then restart the controller.
Requires `app/admin` and its dependencies.

There is no separate `app_defaults.toml`: the loadout is the only enable switch.
Use `//apps disable server_admin_bridge` and restart to stop automatic grants.
The app is removable/restorable through the normal optional-app management path.

## Changes And Limits

- Grants the server login MasterAdmin status on sync without changing `.env`,
  `adminops.toml` or the database.
- Existing explicit MasterAdmin entries/IP restrictions are left unchanged.
  A newly appended server-login entry has an unrestricted IP field.
- This is a broad administrative trust grant, not a read-only monitoring feature.
  Enable only when server-login commands need that authority and dedicated-server
  administration is trusted. It does not install a remote API or OS service.
- Disabling the app does not remove a server login explicitly configured as a
  MasterAdmin elsewhere. Review explicit role settings separately if needed.

## Credits

Nila / PyXaseco project.
