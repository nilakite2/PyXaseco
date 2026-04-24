# PyXaseco

Python 3.12 port of Xaseco 1.16 for **TrackMania Forever (TMF)**.

## Folder structure

```
pyxaseco/
├── main.py                    		# Entry point  (replaces aseco.php)
├── requirements.txt           		# Python libraries
├── config.xml                 		# Your existing config.xml — unchanged
├── plugins.xml                		# Your existing plugins.xml — filenames change (see below)
├── adminops.xml               		# Unchanged
├── bannedips.xml              		# Unchanged
├── dedimania.xml			   		# Unchanged
├── flexitime.xml			   		# Unchanged
├── fufi_menu_config.xml	   		# Unchanged
├── localdatabase.xml		   		# Unchanged
├── rasp.xml				   		# Unchanged
├── records_eyepiece.xml	   		# Unchanged
├── trackhist.txt			   		# Unchanged
│                              
├── panels/					   		# Templates for panel positions
│   ├── AdminBelowChat.xml
│   ├── DonateRightEdge.xml
│   ├── RecordsRightBottom.xml
│   ├── VoteCallVote.xml
│   └── ...
│
├── pyxaseco/				   		# Core controller functions
│   ├── core/
│   │   ├── __init__.py
│   │   ├── gbx_client.py      		# Async GbxRemote 2 TCP client
│   │   ├── event_bus.py       		# Event register/fire system
│   │   ├── config.py          		# XML config parser
│   │   ├── plugin_loader.py   		# Dynamic plugin importer
│   │   └── aseco.py           		# Main Aseco controller
│   │
│   └── models/
│       └── __init__.py        		# Player, Challenge, Server, Record, etc.
│
├── __init__.py
├── helpers.py
│
├── plugins/                   		# Python plugin files
│   ├── fufi/
│   │   └── fufi_menu.xml
│   │
│   ├── jfreu/
│   │   ├── jfreu.bans.xml
│   │   ├── jfreu.config.xml
│   │   └── jfreu.vips.xml
│   │
│   ├── records_eyepiece/
│   │   ├── __init__.py
│   │   ├── config.py              	# XML loading, defaults, dataclasses
│   │   ├── helpers.py				# shared tmx helpers
│   │   ├── helpwin.py         	   	# help and misc support windows
│   │   ├── plugin.py              	# register(), shared state, top-level event wiring
│   │   ├── state.py               	# EyepieceState, runtime helpers
│   │   ├── toplists.py        	   	# generic toplists and /estat windows
│   │   ├── tracklist.py       	   	# /elist window, filters, pagination, author list later
│   │   ├── ui.py               	# builders for big mode UI
│   │   ├── utils.py               	# clip, digest, mode names, shared formatting helpers
│   │   │	
│   │   ├── widgets/
│   │   │   ├── __init__.py
│   │   │   ├── challenge.py       	# challenge widget + last/current/next window -> Done
│   │   │   ├── checkpoint.py      	# checkpoint count + CP delta -> Done
│   │   │   ├── common.py		   	# Shared send/hide/chat helpers
│   │   │   ├── live.py            	# live rankings widget + live rankings window
│   │   │   ├── records_common.py  	# Shared record widget builder
│   │   │   ├── records_local.py   	# local record widget + local records window -> Done
│   │   │   └── records_dedi.py    	# dedimania widget + dedimania window -> Done
│   │   │	
│   │   └── handlers/	
│   │		├── __init__.py	
│   │		├── events.py          	# onSync, onPlayerConnect, onNewChallenge, etc.
│   │		├── actions.py         	# onPlayerManialinkPageAnswer
│   │		└── chat.py            	# /eyepiece /elist /estat /eyeset
│   │	
│	├── chat_help.py           		# Port of chat.help.php
│	├── chat_admin.py          		# Port of chat.admin.php
│	├── jfreu_plugin.py        		# Port of jfreu.plugin.php + jfreu.chat.php
│	├── plugin_cplive_v2_0_5    	# Port of plugin.cplive_v3.php (v3.4.3)
│	└── ...                    		# + other plugins
```

## Running

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

python pyxaseco/main.py config.xml
# or with debug logging:
python pyxaseco/main.py config.xml --debug
```

## Plugin naming convention

PHP filename → Python filename:

| PHP (plugins.xml)            | Python file               | Python (plugins.xml)      |
|------------------------------|---------------------------|---------------------------|
| `chat.help.php`              | `chat_help.py`            | `chat_help`               |
| `plugin.chatlog.php`         | `plugin_chatlog.py`       | `plugin_chatlog`          |
| `plugin.localdatabase.php`   | `plugin_localdatabase.py` | `plugin_localdatabase`    |
| `jfreu.plugin.php`           | `jfreu_plugin.py`         | `jfreu_plugin`            |

The loader strips `.php` and replaces dots with underscores automatically.
Your `plugins.xml` entries can still use the old PHP names (the loader handles it),
or you can update them to the Python names.

## Writing a plugin

```python
# plugins/my_plugin.py

def register(aseco):
    aseco.add_chat_command('hello', 'Says hello')
    aseco.register_event('onChat_hello', chat_hello)
    aseco.register_event('onPlayerConnect', on_player_connect)

async def chat_hello(aseco, command):
    player = command['author']
    await aseco.client.query_ignore_result(
        'ChatSendServerMessageToLogin',
        '$fffHello, ' + player.nickname + '!',
        player.login
    )

async def on_player_connect(aseco, player):
    await aseco.client.query_ignore_result(
        'ChatSendServerMessage',
        '$fff' + player.nickname + ' joined!'
    )
```

## Events

All PHP event names are preserved exactly:

| Event                       | param                        |
|-----------------------------|------------------------------|
| `onStartup`                 | None                         |
| `onSync`                    | None                         |
| `onPlayerConnect`           | Player                       |
| `onPlayerDisconnect`        | Player                       |
| `onChat`                    | [uid, login, text, is_cmd]   |
| `onChat_{command}`          | {'author': Player, 'params'} |
| `onPlayerFinish`            | [uid, login, score]          |
| `onCheckpoint`              | [uid, login, time, lap, cp]  |
| `onNewChallenge`            | Challenge                    |
| `onBeginRace`               | Challenge                    |
| `onEndRace`                 | [rankings, challenge, ...]   |
| `onEndRaceRanking`          | rankings list                |
| `onEndRound`                | None                         |
| `onBeginRound`              | None                         |
| `onEverySecond`             | None                         |
| `onMainLoop`                | None                         |
| `onShutdown`                | None                         |
| `onStatusChangeTo{N}`       | [code, name]                 |
| `onBillUpdated`             | params                       |
| `onPlayerManialinkPageAnswer` | [uid, login, answer]       |
| `onVoteUpdated`             | params                       |
