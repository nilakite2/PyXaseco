# Endless TMX Random

## Purpose

Optional fun-server gameplay: fetch a random TMX map and advance when the selected
record/time trigger is met. It is not needed for normal map rotation or administration.

## Commands

No dedicated public command. Configure it through `//apps config endlesstmxr`.
Administrative map controls remain owned by Admin; random-map requests and
downloads use the existing TMX/Jukebox services.

## Configuration

Enable `app/endlesstmxr` explicitly in `apps.toml`. `app_defaults.toml` controls
`enabled`, `trigger`, TMX sections, excluded styles, announcements, skipped-map
cleanup and the author-time search limit.

## Changes And Limits

- Triggers include author time, TMX WR, Dedimania WR or disabled behavior.
- External-record lookup failures are not silently treated as author-time records.
- Automatically changing maps is intentional here; leave the app disabled on
  single-map/event servers unless that behavior is specifically wanted.
- TMX availability, map type and dedicated-server game/pack compatibility still
  determine whether a downloaded map can be added.

## Credits

Nila / PyXaseco project.
