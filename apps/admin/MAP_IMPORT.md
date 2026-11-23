# TMF bulk TMX map imports

Create a folder named **map_imports** next to the controller's **main.py**
(not inside the dedicated server's Tracks folder). Put a UTF-8 text file
such as **maps.txt** in it. Enter positive TMX track IDs separated by commas,
spaces, or newlines. Lines can contain comments starting with a hash sign.
Each file can contain up to 500 IDs and 32 KiB. Use one file per TMX section.

As an unlocked MasterAdmin on the main server, run **//addfile maps.txt**.
The game edition normally determines the TMX section. You can also use
**//addfile maps.txt tmnf** or specify **tmu**, **tmo**, **tms**, or **tmn**.
The long command is **/admin addfile maps.txt**.

The batch adds maps to the live playlist and its current saved MatchSettings
file without queueing them for immediate play. Duplicate IDs and maps already
in the live rotation are skipped. The controller log records rejected IDs.
Use **//addfile cancel** to stop the batch. A map already being applied may
finish; maps already added are not rolled back.
