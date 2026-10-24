# TMX

## Purpose

Provides TMX map metadata, records/replay information, world-record helpers and
TMX video/GPS browsing. Map download requests/searches are surfaced by Jukebox.

## Commands

| Command | Purpose |
| --- | --- |
| `/tmxinfo` | Show TMX information; supports explicit map/section arguments. |
| `/tmxrecs` | Show TMX records for the current or specified map. |
| `/gps` | Show TMX videos/GPS for the current map. |
| `/gps help`, `/gps latest`, `/gps oldest`, `/gps list` | Help, video selection and listing. |

These are public read commands. `/xlist`, `/add` and `/tmxr` belong to Jukebox.
Administrator-curated `/cgps` links belong to a separate optional app.

## Configuration

No app-specific defaults file. Uses shared TMX services/controller settings and
map metadata. The UI's Current Track widget has its own configuration in UI.

## Changes And Limits

- Background lookups and caching avoid blocking gameplay or requiring a second
  click simply because the first lookup was still loading.
- Handles legacy TMX text decoding and supplies shared WR helpers.
- Native TMF clickable links need HTTP even when the controller's API transport
  uses HTTPS. A video result is not a replay uploaded by this controller.

## Credits

Original TMX Info: Xymph. TMX Video: malun22.
PyXaseco adaptation: Nila / PyXaseco project.
