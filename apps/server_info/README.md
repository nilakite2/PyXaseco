# Server Info

## Purpose

Shows server configuration, runtime information and the health/response timing
of enabled integrations without requiring those optional integrations to exist.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/server` | Open the server/runtime/integration overview. | Everyone; sensitive details ability-filtered |
| `/pyxaseco`, `/xaseco` | Show controller version, uptime, website and credits. | Everyone |
| `/plugins`, `/apps` | List active app runtime entries and capabilities. | Everyone |
| `/nations` | Show connected-player nation information. | Everyone |
| `/uptodate` | Run the supported update-information check. | Administrative checks apply |

`/apps` is an information view; `//apps` is the separate MasterAdmin app manager.

## Configuration

No app-specific defaults file. Uses shared server state, registered capabilities
and existing health measurements. Window presentation follows Platform UI.

## Changes And Limits

- `/server` lists only enabled integrations and uses a refresh control; refreshing
  does not actively probe every external API or guarantee future availability.
- PYXA Stats publishing is a separate optional app. Keeping Server Info loaded
  does not send statistics to a website.
- Native TMF links use HTTP, including `http://github.com/nilakite2/PyXaseco`.
  Python's external API clients may still use HTTPS; that is a separate limitation.

## Credits

XAseco information and update commands: Xymph.
PyXaseco adaptation and runtime overview: Nila / PyXaseco project.
