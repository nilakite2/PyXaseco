# Import TMX Maps in PyXaseco 1.7.1

Put `maps.txt` in this `map_imports` folder, next to your controller's
`main.py`. Do not put it in the dedicated server's `Tracks` or
`MatchSettings` folder.

Save the list as UTF-8. Separate positive TMX track IDs with commas, spaces,
or newlines. Use `#` for comments. For example:

```text
5200696, 11168508
11517174 # Another TMNF map
```

As an unlocked MasterAdmin on the main server, run:

```text
//addfile maps.txt
//addfile maps.txt tmnf
```

The first command uses the server's default TMX section. The second selects
`tmnf` explicitly. Other supported sections are `tmu`, `tmo`, `tms`, and
`tmn`. Use one file per section, with up to 500 IDs and 32 KiB per file.

The importer adds maps to the live rotation and selected MatchSettings without
queueing them for immediate play. Duplicate IDs and maps already in the live
rotation are skipped. Rejection details are written to the controller log.
Use `//addfile cancel` to stop. Maps already saved stay in the playlist.
