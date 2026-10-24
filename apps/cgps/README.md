# Curated GPS

## Purpose

Stores one administrator-selected GPS link per map and provides a browser button.
Independent of TMX Video and its `/gps` command.

## Commands

| Command | Purpose | Access |
| --- | --- | --- |
| `/cgps` | Send the current map's GPS link privately in chat. | Everyone |
| `/cgps help`, `/cgps list` | Show help or browse maps and GPS availability. | Everyone |
| `/cgps add [<map_id>] <link>` | Add a GPS link. | Admin / MasterAdmin |
| `/cgps mod [<map_id>] <link>` | Replace a GPS link. | Admin / MasterAdmin |
| `/cgps rem [<map_id>] [<link>]` | Clear a GPS link. | Admin / MasterAdmin |
| `/cgps del [<map_id>] [<link>]` | Alias for `rem`. | Admin / MasterAdmin |

Omit the map ID to target the current map. Use IDs from `/cgps list`, not TMX IDs;
an exact map UID also works. A trailing deletion link must match the saved link.

## Configuration

Enable `app/cgps` and restart. The `curated_gps` table is created automatically
in the controller database. Configure the optional bar widget in `app_defaults.toml`
or through supported `//apps config cgps` fields.

## Changes And Limits

- The widget opens the GPS in a browser; `/cgps` sends the chat link.
- Missing links show `NO GPS` on the button and `No GPS found for current track!`
  in chat. Removing a link stores SQL NULL while keeping the map's stable ID.
- HTTPS input is converted to HTTP for TMF links. The destination must accept
  HTTP or redirect the browser. Only HTTP/HTTPS URLs are accepted.
- Known map names/UIDs are synchronized without overwriting saved links.
  Removing a map from the playlist keeps its GPS for later reuse.
- F7 controls widget visibility; it is hidden on the score screen.
- Links live in MariaDB: include the database when backing them up.

## Credits

Nila / PyXaseco project.
