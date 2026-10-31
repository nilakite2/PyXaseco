# Sponsor Banner

## Purpose

Optional rotating sponsor images. The entire image opens the sponsor's website;
there is no heading, separate link button or chat announcement.

Defaults: ManiaKarma-sized area (15.76 x 10.75), top-centre position, one sponsor
every 30 seconds, visible in racing and on the score screen. F7 hides/restores
the banner for that player without affecting anyone else.

## Commands

- `//apps config sponsor_banner`: configure enabled flags, position, size,
  interval, ordering and duration through the existing Apps Manager controls.
- `//apps reload sponsor_banner`: reload changes without restarting the controller.

There is no separate public chat command. Edit image/link URLs, local paths and
additional sponsor sections directly in `app_defaults.toml`, then reload.

## Configuration

Enable `app/sponsor_banner` in your loadout and restart the controller once.
The app is listed disabled by default. It depends on Platform Core and UI;
it does not require ManiaKarma itself to be enabled.

Each sponsor has a named section under `[sponsor_banner.sponsors]`:

```toml
[sponsor_banner.sponsors.example]
enabled = true
order = 4
duration_seconds = 0
image_url = "http://example.com/sponsors/banner.png"
image_file = ""
link_url = "http://example.com/"
```

Use exactly one image source. Set `duration_seconds = 0` to use the app's
`interval_seconds`; a positive value gives that sponsor its own display time.
Disabled entries are skipped. Lower `order` values come first; equal values
retain file order. An empty/all-disabled list hides the widget.

Set `show_in_race` / `show_on_score` independently. Position and size are
configurable; changing them does not move or resize ManiaKarma. Prepare images
for the chosen rectangular area: TMF scales each image to the quad dimensions.

## Local Images

A local file is a source reference, not automatic hosting. Players still need
a public HTTP(S) address from which their game can fetch that file.

For example, if your existing web server serves `C:/Sponsors` at
`http://your-site.example/sponsors/`, configure:

```toml
[sponsor_banner]
local_directory = "C:/Sponsors"
asset_base_url = "http://your-site.example/sponsors/"

[sponsor_banner.sponsors.local_example]
enabled = true
order = 4
duration_seconds = 0
image_url = ""
image_file = "my-banner.png"
link_url = "http://example.com/"
```

Merge these fields into the existing sections; do not duplicate the root table.
Relative `local_directory` paths start inside `apps/sponsor_banner/`. Nested
filenames are supported. Files must exist inside the configured directory;
traversal and files resolving outside it are rejected. Filenames are URL-encoded.
No local absolute path is exposed in ManiaLink markup.

## Changes And Limits

- Includes the supplied Hetzner, ManiaActu and ESL image/link entries.
- Direct images support the documented TMF JPG, PNG, TGA, DDS and GIF formats.
  Use addresses reachable by the game, not image-search pages or browser challenges.
  The app preserves HTTP(S) image URLs; it does not bypass redirects, authentication
  or TLS restrictions. Use your own reachable HTTP host if an external source fails.
- Browser destination links are normalised to HTTP for TMF; the external browser
  may then follow a website's HTTPS redirect.
- At most 100 sponsor entries; durations are 1-86400 seconds. Images are displayed
  by clients, not downloaded, resized, cached or served by the controller.
- Rotation continues through map changes. Reconnecting players see the current
  sponsor; configuration reload restarts the sequence at the first enabled entry.
- Uses shared, deduplicated widget delivery. No per-second network image requests,
  additional Python libraries, database tables, web service or background threads
  dedicated to the banner are added.

## Credits

Nila / PyXaseco project. Sponsor images remain externally hosted and are not
bundled with the app.
