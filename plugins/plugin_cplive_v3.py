"""
plugin_cplive_v3.py - Ported from plugin.cplive_v3.php (v3.4.3) - https://github.com/join-red/checkpoints_live/.
"""

from __future__ import annotations

import hashlib
import html
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pyxaseco.helpers import display_manialink, strip_colors, strip_sizes

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco
    from pyxaseco.models import Player

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------

VERSION = "3.4.3"

COLORS = {
    "Title": "FFE",
    "TrackText": "ABC",
    "TrackCPs": "9B1",
    "CPNumber": "F93",
    "Time": "FFC",
    "Mono": "ABC",
    "MonoSystem": "333",
    "DeltaPos": "FAA",
    "DeltaNeg": "AAF",
}

FALLBACK_DRIVER_TIME_STR = "--.--"
FALLBACK_SPECTATOR_TIME_STR = ""
SPECTATOR_CP_PLACEHOLDER = "-"

ID_TITLE_BAR = 1928378
ID_LIST = 1928379

ANSWER_TOGGLE_HUD = "01928390"
ANSWER_SWITCH_COLOR = "01928396"
ANSWER_SPECTATE_BASE = 71928400

TOGGLE_KEY = 0
KEYS = ["", "F5", "F6", "F7"]

CFG_TOUCH_NONE = 0
CFG_TOUCH_SLICE = 1
CFG_TOUCH_ROWS = 2
CFG_TOUCH_PAYLOAD = 4

CONFIG_TOUCH = {
    "MAX_DISPLAY_ROWS": CFG_TOUCH_SLICE,
    "SHOW_SPECTATORS": CFG_TOUCH_SLICE,
    "LEADER_MODE": CFG_TOUCH_ROWS,
    "USE_SPECTATOR_ICON": CFG_TOUCH_ROWS,
    "SHOW_SPECTATOR_TARGETS": CFG_TOUCH_ROWS,
    "ALLOW_NICK_STYLE_TOGGLE": CFG_TOUCH_PAYLOAD,
    "TOGGLE_KEY": CFG_TOUCH_PAYLOAD,
    "POS_X": CFG_TOUCH_PAYLOAD,
    "POS_Y": CFG_TOUCH_PAYLOAD,
    "STRICT_MODE": CFG_TOUCH_NONE,
    "WIDGET_UPDATE_INTERVAL": CFG_TOUCH_NONE,
    "MIN_WIDGET_UPDATE_INTERVAL": CFG_TOUCH_NONE,
}

DIRTY_SLICE = 1
DIRTY_ROWS = 2

CP_CELL_NUMBER = 0
CP_CELL_FINISH = 1
CP_CELL_SPEC_ICON = 2
CP_CELL_SPEC_TEXT = 3

TIME_CELL_DRIVER_UNKNOWN = 0
TIME_CELL_DRIVER_TIME = 1
TIME_CELL_DRIVER_DELTA = 2
TIME_CELL_SPEC_FALLBACK = 3
TIME_CELL_SPEC_EMPTY = 4
TIME_CELL_SPEC_AUTO = 5
TIME_CELL_SPEC_TARGET = 6


# ---------------------------------------------------------------------------
# Runtime config
# ---------------------------------------------------------------------------

MAX_DISPLAY_ROWS = 24
POS_X = -64.4
POS_Y = 22.7

WIDGET_UPDATE_INTERVAL = 100
MIN_WIDGET_UPDATE_INTERVAL = 50
STRICT_MODE = False
LEADER_MODE = False

ALLOW_NICK_STYLE_TOGGLE = True
PLAIN_NICKS = False

SHOW_SPECTATORS = True
USE_SPECTATOR_ICON = True
SHOW_SPECTATOR_TARGETS = True


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class PlayerState:
    Login: str
    Pid: int
    PlainNicks: bool = False
    Collapsed: bool = False
    NicknamePlainXml: str = ""
    NicknameColoredXml: str = ""
    CPNumber: int = 0
    RawTime: int = 0
    CPTimes: list[int] = field(default_factory=lambda: [0])
    Spectator: bool = False
    SpectatorStatus: int | None = None
    SpectatesPid: int = 0
    AutoTarget: bool = False
    SpectateAction: str = ""
    TieKey: int = 0

    SentHash: str = ""
    LastUpdate: int = 0
    PendingGlobal: bool = False
    PendingLocal: bool = False
    LocalDueAt: int | None = None


@dataclass
class CPLiveStats:
    add_calls_by_variant: dict[Any, int] = field(default_factory=dict)
    add_calls_no_csl_by_variant: dict[Any, int] = field(default_factory=dict)
    bundled_by_variant: dict[Any, int] = field(default_factory=dict)

    hash_hits: int = 0
    row_model_hash_hits: int = 0

    total_add_calls: int = 0
    total_add_calls_no_csl: int = 0
    total_bundled: int = 0
    total_xml_bytes: int = 0
    total_xml_bytes_no_csl: int = 0

    total_flushes: int = 0
    forced_flushes: int = 0
    empty_flushes: int = 0

    checkpoints: int = 0
    finishes: int = 0
    connects: int = 0
    disconnects: int = 0
    spec_changes: int = 0
    target_changes: int = 0
    local_toggles: int = 0
    config_changes: int = 0
    target_forces: int = 0

    widget_reset_at: int = 0

    def reset(self):
        self.add_calls_by_variant.clear()
        self.add_calls_no_csl_by_variant.clear()
        self.bundled_by_variant.clear()

        self.hash_hits = 0
        self.row_model_hash_hits = 0

        self.total_add_calls = 0
        self.total_add_calls_no_csl = 0
        self.total_bundled = 0
        self.total_xml_bytes = 0
        self.total_xml_bytes_no_csl = 0

        self.total_flushes = 0
        self.forced_flushes = 0
        self.empty_flushes = 0

        self.checkpoints = 0
        self.finishes = 0
        self.connects = 0
        self.disconnects = 0
        self.spec_changes = 0
        self.target_changes = 0
        self.local_toggles = 0
        self.config_changes = 0
        self.target_forces = 0

        self.widget_reset_at = _ms()

    def current_widget_lifetime(self) -> int:
        return _ms() - self.widget_reset_at

    def note_dispatch(
        self,
        physical_variant_key: Any,
        variant_counts: dict[Any, int],
        bundle_counts: dict[Any, int],
        xml_bytes: int,
    ):
        recipient_count = sum(variant_counts.values())
        bundle_count = sum(bundle_counts.values())

        for k, v in variant_counts.items():
            self.add_calls_no_csl_by_variant[k] = self.add_calls_no_csl_by_variant.get(k, 0) + v
        for k, v in bundle_counts.items():
            self.bundled_by_variant[k] = self.bundled_by_variant.get(k, 0) + v

        self.total_add_calls += 1
        self.total_add_calls_no_csl += recipient_count
        self.total_bundled += bundle_count
        self.total_xml_bytes += xml_bytes
        self.total_xml_bytes_no_csl += xml_bytes * recipient_count

        self.add_calls_by_variant[physical_variant_key] = (
            self.add_calls_by_variant.get(physical_variant_key, 0) + 1
        )

    def variant_label(self, key: Any) -> str:
        if key == "c":
            return "collapsed"
        if key == "mixed":
            return "mixed"
        plain = bool(key & 1)
        spec = bool(key & 2)
        return f'{"spec" if spec else "driver"} ({"plain" if plain else "color"})'


# ---------------------------------------------------------------------------
# Disabled object
# ---------------------------------------------------------------------------

class _DisabledCPLive:
    enabled = False

    async def handle_chat(self, aseco: "Aseco", command: dict):
        login = command["author"].login
        await _send_chat(aseco, login, "CP Live is disabled: a MasterAdmin must enable it")

    def __getattr__(self, _name):
        async def _noop(*_args, **_kwargs):
            return None
        return _noop


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class _CPLive:
    enabled = True

    def __init__(self):
        self.players: dict[str, PlayerState] = {}
        self.pid_to_login: dict[int, str] = {}
        self.spec_action_to_login: dict[str, str] = {}

        self.total_cps = 0
        self.challenge_seed = 0
        self.leader_login: str | None = None

        self.should_render = True

        self.dirty_mask = DIRTY_SLICE | DIRTY_ROWS
        self.shown_logins: list[str] = []
        self.list_rows: list[dict[str, Any]] = []
        self.list_hash_bin = ""

        self.last_global_update = 0
        self.global_due_at: int | None = None

        self.payload_cache: dict[Any, dict[str, str]] = {}
        self.xml_title_bar = ""
        self.xml_title_bar_collapsed = ""
        self.xml_empty = ""
        self.xml_title_bar_collapsed_hash = ""
        self.xml_empty_hash = ""

        self.stats = CPLiveStats()
        self.cache_static_xml()

    # -------------------- lifecycle --------------------

    async def init(self, aseco: "Aseco"):
        self.players.clear()
        self.pid_to_login.clear()
        self.spec_action_to_login.clear()
        self.payload_cache.clear()

        await _update_track_info(self, aseco)
        await self.reset(aseco, hydrate_spec_status=True)
        await _send_chat_global(aseco, f"Started CP Live v{VERSION}")

    async def reset(self, aseco: "Aseco", hydrate_spec_status: bool = False):
        for player in aseco.server.players.all():
            login = player.login
            if login not in self.players:
                self.init_player(player)

            self.reset_player_time(login)

            if hydrate_spec_status:
                await self.sync_spectator_state(aseco, login, player)
            else:
                # Use spectatorstatus (set by aseco.py from the GBX callback) when
                # available; fall back to isspectator if not yet set.
                raw_status = getattr(player, "spectatorstatus", None)
                if raw_status is not None:
                    spec_status = int(raw_status)
                    is_spec = (spec_status % 10) != 0
                    self.players[login].SpectatorStatus = spec_status
                    self.players[login].AutoTarget = ((spec_status // 1000) % 10) != 0 if is_spec else False
                    self.players[login].SpectatesPid = (spec_status // 10000) if is_spec else 0
                else:
                    is_spec = bool(getattr(player, "isspectator", False))
                    if not is_spec:
                        self.players[login].SpectatorStatus = 0
                        self.players[login].SpectatesPid = 0
                        self.players[login].AutoTarget = False
                self.players[login].Spectator = is_spec

        self.should_render = True
        self.leader_login = None
        self.shown_logins = []
        self.list_rows = []
        self.list_hash_bin = ""
        self.payload_cache = {}
        self.last_global_update = 0

        self.dirty_mask = DIRTY_SLICE | DIRTY_ROWS

        self.stats.reset()
        self.schedule_global_delivery(include_collapsed=True)
        await self.flush(aseco, force_now=True)

    def init_player(self, player: "Player"):
        login = player.login
        pid = int(getattr(player, "pid", 0) or 0)
        nickname = getattr(player, "nickname", "") or ""
        spectate_action = f"{ANSWER_SPECTATE_BASE + pid:08d}"

        state = PlayerState(
            Login=login,
            Pid=pid,
            PlainNicks=PLAIN_NICKS,
            Collapsed=False,
            NicknamePlainXml="$" + COLORS["Mono"] + strip_colors(strip_sizes(nickname), for_tm=True),
            NicknameColoredXml=_strip_sizes_php(nickname),
            CPNumber=0,
            RawTime=0,
            CPTimes=[0],
            Spectator=bool(getattr(player, "isspectator", False)),
            SpectatorStatus=None,
            SpectatesPid=0,
            AutoTarget=False,
            SpectateAction=spectate_action,
            TieKey=zlib_crc32(login) ^ self.challenge_seed,
        )
        self.players[login] = state
        self.spec_action_to_login[spectate_action] = login
        self.pid_to_login[pid] = login

    def reset_player_time(self, login: str):
        p = self.players[login]
        p.CPNumber = 0
        p.RawTime = 0
        p.CPTimes = [0]

    # -------------------- spectator sync --------------------

    async def sync_spectator_state(self, aseco: "Aseco", login: str, player_obj: "Player" | None = None):
        """
        Canonical spectator-state sync from the server.

        PHP CPLive derives Spectator from SpectatorStatus % 10 != 0 — NOT from
        IsSpectator. We do the same: call GetPlayerInfo(login, 1) which returns
        the current SpectatorStatus integer, then decode everything from that.

        SpectatorStatus encoding (packed int):
            digit 0  (status % 10)         : != 0 → is spectator
            digits 1-2 (status//10 % 100)  : spectator mode (0=normal,1=linked,2=free)
            digit 3  (status//1000 % 10)   : != 0 → auto-target (server chooses target)
            digits 4-7 (status//10000)     : PID of spectated player (0 = none)
        """
        p = self.players.get(login)
        if not p:
            return

        # If aseco.py has already decoded SpectatorStatus from the GBX callback
        # and stored it on the Player object, use that to avoid a round-trip.
        # Otherwise fall back to GetPlayerInfo.
        raw_from_player = None
        if player_obj is not None:
            raw_from_player = getattr(player_obj, "spectatorstatus", None)

        if raw_from_player is not None:
            spec_status = int(raw_from_player)
        else:
            try:
                info = await aseco.client.query("GetPlayerInfo", login, 1) or {}
            except Exception:
                info = {}
            spec_status = int(info.get("SpectatorStatus", 0) or 0)

    # Canonical spectator detection uses the low digit of spectatorstatus.
        live_is_spec = (spec_status % 10) != 0

        p.SpectatorStatus = spec_status
        p.Spectator = live_is_spec

        if not live_is_spec:
            p.AutoTarget = False
            p.SpectatesPid = 0
            return

        p.AutoTarget = ((spec_status // 1000) % 10) != 0
        p.SpectatesPid = spec_status // 10000

        # Keep the player object in sync so other plugins see correct state
        live_player = player_obj
        if live_player is None:
            try:
                live_player = aseco.server.players.get_player(login)
            except Exception:
                live_player = None
        if live_player is not None:
            live_player.isspectator = live_is_spec

    def is_login_possibly_shown(self, login: str) -> bool:
        if (self.dirty_mask & DIRTY_SLICE) != 0:
            return True
        return login in self.shown_logins

    # -------------------- refresh scheduling --------------------

    def request_slice_refresh(self):
        self.dirty_mask |= DIRTY_SLICE | DIRTY_ROWS
        self.schedule_global_delivery(include_collapsed=False)

    def request_row_refresh(self):
        self.dirty_mask |= DIRTY_ROWS
        self.schedule_global_delivery(include_collapsed=False)

    def request_payload_refresh(self):
        self.payload_cache = {}
        self.schedule_global_delivery(include_collapsed=False)

    def schedule_global_delivery(self, include_collapsed: bool):
        for p in self.players.values():
            p.PendingGlobal = include_collapsed or (not p.Collapsed)
        self.reschedule_global_due_at()

    def request_local_refresh(self, login: str, force_now: bool = False):
        p = self.players[login]
        p.PendingLocal = True

        if force_now or not STRICT_MODE:
            due_at = _ms()
        else:
            latest = max(self.last_global_update, p.LastUpdate)
            due_at = max(_ms(), latest + WIDGET_UPDATE_INTERVAL)

        if p.LocalDueAt is None or due_at < p.LocalDueAt:
            p.LocalDueAt = due_at

    def reschedule_pending_locals(self):
        now = _ms()
        for p in self.players.values():
            if not p.PendingLocal:
                continue
            if not STRICT_MODE:
                p.LocalDueAt = now
                continue
            latest = max(self.last_global_update, p.LastUpdate)
            p.LocalDueAt = max(now, latest + WIDGET_UPDATE_INTERVAL)

    def reschedule_global_due_at(self):
        self.global_due_at = None
        for p in self.players.values():
            if not p.PendingGlobal:
                continue
            due_at = max(
                self.last_global_update + WIDGET_UPDATE_INTERVAL,
                p.LastUpdate + WIDGET_UPDATE_INTERVAL,
            )
            if self.global_due_at is None or due_at < self.global_due_at:
                self.global_due_at = due_at

    def is_flush_due(self, now: int) -> bool:
        if self.global_due_at is not None and now >= self.global_due_at:
            return True
        for p in self.players.values():
            if p.PendingLocal and p.LocalDueAt is not None and now >= p.LocalDueAt:
                return True
        return False

    # -------------------- slice / rows --------------------

    def rebuild_shown_slice(self):
        logins = []
        for login, p in self.players.items():
            if (not p.Spectator) or SHOW_SPECTATORS:
                logins.append(login)

        logins.sort(
            key=lambda login: (
                1 if (SHOW_SPECTATORS and self.players[login].Spectator) else 0,
                -int(self.players[login].CPNumber),
                int(self.players[login].RawTime),
                int(self.players[login].TieKey),
                login.lower(),
            )
        )

        self.shown_logins = logins[:MAX_DISPLAY_ROWS]
        self.leader_login = None
        for login in self.shown_logins:
            p = self.players[login]
            if not p.Spectator and p.CPNumber > 0:
                self.leader_login = login
                break

        self.dirty_mask &= ~DIRTY_SLICE

    def build_row_view(self, login: str, leader_times: list[int] | None):
        p = self.players[login]
        cp = int(p.CPNumber)
        cp_cell_value = 0
        time_cell_value: str | int = ""

        if cp == self.total_cps and cp > 0:
            cp_cell_kind = CP_CELL_FINISH
        elif p.Spectator:
            cp_cell_kind = CP_CELL_SPEC_ICON if USE_SPECTATOR_ICON else CP_CELL_SPEC_TEXT
        else:
            cp_cell_kind = CP_CELL_NUMBER
            cp_cell_value = cp

        if p.Spectator:
            if not SHOW_SPECTATOR_TARGETS:
                time_cell_kind = TIME_CELL_SPEC_FALLBACK
            elif p.AutoTarget:
                time_cell_kind = TIME_CELL_SPEC_AUTO
            elif p.SpectatesPid > 0 and p.SpectatesPid in self.pid_to_login:
                target_login = self.pid_to_login[p.SpectatesPid]
                time_cell_kind = TIME_CELL_SPEC_TARGET
                time_cell_value = self.players[target_login].NicknamePlainXml
            else:
                time_cell_kind = TIME_CELL_SPEC_EMPTY
        elif cp == 0:
            time_cell_kind = TIME_CELL_DRIVER_UNKNOWN
        elif LEADER_MODE and self.leader_login and login != self.leader_login and leader_times and cp < len(leader_times):
            time_cell_kind = TIME_CELL_DRIVER_DELTA
            time_cell_value = p.RawTime - leader_times[cp]
        else:
            time_cell_kind = TIME_CELL_DRIVER_TIME
            time_cell_value = p.RawTime

        return {
            "Login": login,
            "IsSpectator": p.Spectator,
            "CpCellKind": cp_cell_kind,
            "CpCellValue": cp_cell_value,
            "TimeCellKind": time_cell_kind,
            "TimeCellValue": time_cell_value,
        }

    def ensure_rows_up_to_date(self):
        if self.dirty_mask & DIRTY_SLICE:
            self.rebuild_shown_slice()

        if not (self.dirty_mask & DIRTY_ROWS):
            return

        rows = []
        leader_times = None
        if LEADER_MODE and self.leader_login is not None:
            leader_times = self.players[self.leader_login].CPTimes

        ctx = hashlib.md5()
        for login in self.shown_logins:
            row = self.build_row_view(login, leader_times)
            rows.append(row)
            self.hash_row_model(ctx, row)

        new_hash_bin = ctx.digest()
        self.list_rows = rows

        if new_hash_bin != self.list_hash_bin:
            self.list_hash_bin = new_hash_bin
            self.payload_cache = {}
        else:
            self.stats.row_model_hash_hits += 1

        self.dirty_mask &= ~DIRTY_ROWS

    @staticmethod
    def hash_row_model(ctx: "hashlib._Hash", row: dict[str, Any]):
        payload = (
            f'{row["Login"]}\0'
            f'{"1" if row["IsSpectator"] else "0"}\0'
            f'{row["CpCellKind"]}\0'
            f'{row["CpCellValue"]}\0'
            f'{row["TimeCellKind"]}\0'
            f'{row["TimeCellValue"]}\0'
        )
        ctx.update(payload.encode("utf-8", errors="replace"))

    # -------------------- payload variants --------------------

    def get_variant_key(self, p: PlayerState):
        if p.Collapsed:
            return "c"
        plain = 1 if (ALLOW_NICK_STYLE_TOGGLE and p.PlainNicks) else 0
        spec = 2 if p.Spectator else 0
        return plain | spec

    def get_payload(self, variant_key: Any):
        if variant_key == "c":
            return {"xml": self.xml_title_bar_collapsed, "hash": self.xml_title_bar_collapsed_hash}

        if variant_key in self.payload_cache:
            return self.payload_cache[variant_key]

        viewer_prefers_plain = bool(variant_key & 1)
        viewer_is_spectator = bool(variant_key & 2)

        xml = "<manialinks>" + self.xml_title_bar + self.build_list_xml(
            viewer_prefers_plain,
            viewer_is_spectator,
        ) + "</manialinks>"

        payload = {"xml": xml, "hash": hashlib.md5(xml.encode("utf-8")).hexdigest()}
        self.payload_cache[variant_key] = payload
        return payload

    # -------------------- XML builders --------------------

    def cache_static_xml(self):
        self.xml_title_bar_collapsed = (
            "<manialinks>"
            f'<manialink id="{ID_TITLE_BAR}"><frame posn="{POS_X} {POS_Y}">'
            f'<quad posn="0 0 -10" sizen="0 0" action="{ANSWER_TOGGLE_HUD}" actionkey="{TOGGLE_KEY}"/>'
            '<quad posn="0 0 0" sizen="6.8 2" halign="left" valign="center" style="BgsPlayerCard" substyle="BgCard"/>'
            f'<label scale="0.45" posn="0.4 0.1 0.1" halign="left" valign="center" style="TextRaceMessage" text="$'
            + COLORS["Title"] + ' CP Live"/>'
            f'<quad posn="4.9 0 0.12" sizen="1.8 1.8" halign="left" valign="center" style="Icons64x64_1" substyle="Camera" action="{ANSWER_TOGGLE_HUD}"/>'
            "</frame></manialink>"
            f'<manialink id="{ID_LIST}" />'
            "</manialinks>"
        )
        self.xml_empty = (
            "<manialinks>"
            f'<manialink id="{ID_TITLE_BAR}" />'
            f'<manialink id="{ID_LIST}" />'
            "</manialinks>"
        )
        self.xml_title_bar_collapsed_hash = hashlib.md5(
            self.xml_title_bar_collapsed.encode("utf-8")
        ).hexdigest()
        self.xml_empty_hash = hashlib.md5(self.xml_empty.encode("utf-8")).hexdigest()

    def update_title_bar_xml(self) -> bool:
        track_cps = max(0, self.total_cps - 1)
        hud = (
            f'<manialink id="{ID_TITLE_BAR}"><frame posn="{POS_X} {POS_Y}">'
            f'<quad posn="0 0 -10" sizen="0 0" action="{ANSWER_TOGGLE_HUD}" actionkey="{TOGGLE_KEY}"/>'
            f'<quad posn="0 0 0" sizen="21 2" halign="left" valign="center" style="BgsPlayerCard" substyle="BgCard" action="{ANSWER_SWITCH_COLOR}"/>'
            f'<label scale="0.45" posn="0.4 0.1 0.1" halign="left" valign="center" style="TextRaceMessage" text="$'
            + COLORS["Title"] + ' Checkpoints Live"/>'
            f'<label scale="0.45" posn="10.5 0.1 0.1" halign="left" valign="center" style="TextRaceMessage" text="$'
            + COLORS["TrackText"] + 'Track CPs:"/>'
            f'<label scale="0.45" posn="16.25 0.1 0.1" halign="left" valign="center" style="TextRaceMessage" text="$'
            + COLORS["TrackCPs"] + str(track_cps) + '"/>'
            f'<quad posn="19 0 0.12" sizen="1.8 1.8" halign="left" valign="center" style="Icons64x64_1" substyle="Close" action="{ANSWER_TOGGLE_HUD}"/>'
            "</frame></manialink>"
        )
        if hud == self.xml_title_bar:
            return False
        self.xml_title_bar = hud
        return True

    def build_list_xml(self, viewer_prefers_plain: bool, viewer_is_spectator: bool) -> str:
        hud = [f'<manialink id="{ID_LIST}">']
        y = POS_Y - 1.9

        for row in self.list_rows:
            login = row["Login"]
            p = self.players[login]
            hud.append(f'<frame posn="{POS_X} {y}">')

            if viewer_is_spectator and not row["IsSpectator"]:
                hud.append(
                    f'<quad posn="0 0 -0.5" sizen="21 1.8" halign="left" valign="center" style="Bgs1InRace" substyle="NavButton" action="{p.SpectateAction}"/>'
                )

            kind = row["CpCellKind"]
            if kind == CP_CELL_FINISH:
                hud.append(
                    '<quad posn="3.02 0 0.06" sizen="1.6 1.6" halign="right" valign="center" style="BgRaceScore2" substyle="Warmup"/>'
                )
            elif kind == CP_CELL_SPEC_ICON:
                hud.append(
                    '<quad posn="1.98 0 0.06" sizen="1.2 1.2" halign="left" valign="center" style="Icons64x64_1" substyle="Camera"/>'
                )
            elif kind == CP_CELL_SPEC_TEXT:
                hud.append(
                    f'<label scale="0.48" posn="3 0.1 0.1" halign="right" valign="center" style="TextRaceMessage" text="${COLORS["CPNumber"]}{SPECTATOR_CP_PLACEHOLDER}"/>'
                )
            else:
                hud.append(
                    f'<label scale="0.48" posn="3 0.1 0.1" halign="right" valign="center" style="TextRaceMessage" text="${COLORS["CPNumber"]}{row["CpCellValue"]}"/>'
                )

            tkind = row["TimeCellKind"]
            tval = row["TimeCellValue"]
            if tkind == TIME_CELL_DRIVER_UNKNOWN:
                hud.append(
                    f'<label scale="0.48" posn="8.5 0.15 0.1" sizen="10.9 2" halign="right" valign="center" style="TextRaceMessage" text="${COLORS["Time"]}{FALLBACK_DRIVER_TIME_STR}"/>'
                )
            elif tkind == TIME_CELL_DRIVER_DELTA:
                hud.append(
                    f'<label scale="0.48" posn="8.5 0.1 0.1" sizen="10.9 2" halign="right" valign="center" style="TextRaceMessage" text="{_format_time(int(tval), True)}"/>'
                )
            elif tkind == TIME_CELL_DRIVER_TIME:
                hud.append(
                    f'<label scale="0.48" posn="8.5 0.1 0.1" sizen="10.9 2" halign="right" valign="center" style="TextRaceMessage" text="${COLORS["Time"]}{_format_time(int(tval))}"/>'
                )
            elif tkind == TIME_CELL_SPEC_FALLBACK:
                hud.append(
                    f'<label scale="0.48" posn="8.5 0.1 0.1" sizen="10.9 2" halign="right" valign="center" style="TextRaceMessage" text="${COLORS["Time"]}{FALLBACK_SPECTATOR_TIME_STR}"/>'
                )
            elif tkind == TIME_CELL_SPEC_EMPTY:
                pass
            elif tkind == TIME_CELL_SPEC_AUTO:
                hud.append(
                    f'<label scale="0.35" posn="8.5 -0.02 0.1" sizen="10.9 2" halign="right" valign="center" style="TextRaceMessage" text="${COLORS["MonoSystem"]}(auto)"/>'
                )
            else:
                hud.append(
                    f'<label scale="0.35" posn="8.5 -0.02 0.1" sizen="10.9 2" halign="right" valign="center" style="TextRaceMessage" text="{tval}"/>'
                )

            nickname = p.NicknamePlainXml if viewer_prefers_plain else p.NicknameColoredXml
            hud.append(
                f'<label scale="0.48" posn="8.8 0.1 0.1" sizen="24.6 2" halign="left" valign="center" style="TextRaceMessage" text="{nickname}"/>'
            )
            hud.append("</frame>")
            y -= 1.8

        hud.append("</manialink>")
        return "".join(hud)

    # -------------------- sending / flushing --------------------

    async def destroy_widget_ui(self, aseco: "Aseco"):
        if not self.should_render:
            return

        self.should_render = False
        self.dirty_mask = 0
        self.global_due_at = None
        self.payload_cache = {}

        for p in self.players.values():
            p.PendingGlobal = False
            p.PendingLocal = False
            p.LocalDueAt = None

        now = _ms()
        await _send_ml_global(aseco, self.xml_empty, 1, False)

        for p in self.players.values():
            p.SentHash = self.xml_empty_hash
            p.LastUpdate = now

    async def flush(self, aseco: "Aseco", force_now: bool = False):
        if not self.should_render:
            return

        now = _ms()
        if not force_now and not self.is_flush_due(now):
            return

        self.stats.total_flushes += 1
        if force_now:
            self.stats.forced_flushes += 1

        self.ensure_rows_up_to_date()

        desired: dict[str, dict[str, Any]] = {}
        for login, player in self.players.items():
            variant_key = self.get_variant_key(player)
            payload = self.get_payload(variant_key)
            desired[login] = payload | {"variantKey": variant_key}

            matched = (payload["hash"] == player.SentHash)
            had_pending = player.PendingGlobal or player.PendingLocal

            if player.PendingGlobal and matched:
                player.PendingGlobal = False
            if player.PendingLocal and matched:
                player.PendingLocal = False
                player.LocalDueAt = None
            if had_pending and matched:
                self.stats.hash_hits += 1

        groups: dict[str, dict[str, Any]] = {}
        consumed_global = False

        for login, player in self.players.items():
            desired_hash = desired[login]["hash"]
            if desired_hash == player.SentHash:
                continue

            due_global = player.PendingGlobal and (
                force_now or (
                    self.global_due_at is not None
                    and now >= self.global_due_at
                    and now >= (player.LastUpdate + WIDGET_UPDATE_INTERVAL)
                )
            )
            due_local = player.PendingLocal and (
                force_now or (
                    player.LocalDueAt is not None and now >= player.LocalDueAt
                )
            )

            if not due_global and not due_local:
                continue

            if desired_hash not in groups:
                groups[desired_hash] = {
                    "xml": desired[login]["xml"],
                    "xmlBytes": len(desired[login]["xml"].encode("utf-8")),
                    "variantKeys": {},
                    "variantCounts": {},
                    "bundleCounts": {},
                    "logins": {},
                }

            groups[desired_hash]["logins"][login] = True
            variant_key = desired[login]["variantKey"]
            groups[desired_hash]["variantKeys"][variant_key] = True
            groups[desired_hash]["variantCounts"][variant_key] = groups[desired_hash]["variantCounts"].get(variant_key, 0) + 1

            if due_global:
                consumed_global = True

        if not groups:
            self.stats.empty_flushes += 1
            self.reschedule_global_due_at()
            return

        for login, player in self.players.items():
            desired_hash = desired[login]["hash"]
            if desired_hash == player.SentHash or desired_hash not in groups:
                continue
            if login not in groups[desired_hash]["logins"]:
                groups[desired_hash]["logins"][login] = True
                variant_key = desired[login]["variantKey"]
                groups[desired_hash]["variantKeys"][variant_key] = True
                groups[desired_hash]["variantCounts"][variant_key] = groups[desired_hash]["variantCounts"].get(variant_key, 0) + 1
                groups[desired_hash]["bundleCounts"][variant_key] = groups[desired_hash]["bundleCounts"].get(variant_key, 0) + 1

        for hsh, group in groups.items():
            logins = list(group["logins"].keys())
            if not logins:
                continue

            variant_keys = list(group["variantKeys"].keys())
            physical_variant_key = variant_keys[0] if len(variant_keys) == 1 else "mixed"

            self.stats.note_dispatch(
                physical_variant_key,
                group["variantCounts"],
                group["bundleCounts"],
                group["xmlBytes"],
            )

            await _send_ml_logins(aseco, ",".join(logins), group["xml"], 0, False)

            for login in logins:
                p = self.players[login]
                p.SentHash = hsh
                p.LastUpdate = now
                p.PendingGlobal = False
                p.PendingLocal = False
                p.LocalDueAt = None

        if consumed_global:
            self.last_global_update = now

        self.reschedule_global_due_at()

    # -------------------- chat commands --------------------

    async def handle_chat(self, aseco: "Aseco", command: dict):
        login = command["author"].login
        args = _parse_command_params(command.get("params", ""))
        cmd = args[0]

        admin_cmds = {
            "refresh", "strict", "rows", "leader", "specs",
            "specmarker", "spectarget", "enable", "disable",
        }

        if cmd in admin_cmds and not _is_masteradmin(aseco, login):
            await _send_chat(aseco, login, "You don't have the required admin rights to do that!")
            return

        if cmd == "color":
            await self.toggle_player_ui_flag(aseco, login, "PlainNicks")
            return

        if cmd == "toggle":
            await self.toggle_player_ui_flag(aseco, login, "Collapsed")
            return

        if cmd == "strict":
            if len(args) < 2:
                await _send_chat(aseco, login, f'CP Live strict mode is {"enabled" if STRICT_MODE else "disabled"}')
                return
            _toggle_config("STRICT_MODE")
            await _send_chat_global(aseco, f'CP Live strict mode has been {"enabled" if STRICT_MODE else "disabled"}')
            return

        if cmd == "leader":
            if len(args) < 2:
                await _send_chat(aseco, login, f'CP Live leader mode is {"enabled" if LEADER_MODE else "disabled"}')
                return
            _toggle_config("LEADER_MODE")
            self.request_row_refresh()
            await _send_chat_global(aseco, f'CP Live leader mode has been {"enabled" if LEADER_MODE else "disabled"}')
            await self.flush(aseco, force_now=True)
            return

        if cmd == "refresh":
            if len(args) < 2 or not args[1].isdigit():
                await _send_chat(aseco, login, f"Current CP Live update interval is {WIDGET_UPDATE_INTERVAL} ms")
                return
            new_val = max(MIN_WIDGET_UPDATE_INTERVAL, min(3600000, int(args[1])))
            old = WIDGET_UPDATE_INTERVAL
            _set_config("WIDGET_UPDATE_INTERVAL", new_val)
            self.reschedule_pending_locals()
            self.reschedule_global_due_at()
            await _send_chat_global(aseco, f"CP Live update interval has been changed from {old} ms to {new_val} ms")
            return

        if cmd == "rows":
            if len(args) < 2 or not args[1].isdigit():
                await _send_chat(aseco, login, f"Current CP Live number of rows is {MAX_DISPLAY_ROWS} row{'s' if MAX_DISPLAY_ROWS != 1 else ''}")
                return
            new_val = max(1, min(50, int(args[1])))
            old = MAX_DISPLAY_ROWS
            _set_config("MAX_DISPLAY_ROWS", new_val)
            self.request_slice_refresh()
            await _send_chat_global(aseco, f"CP Live number of rows has been changed from {old} row{'s' if old != 1 else ''} to {new_val} row{'s' if new_val != 1 else ''}")
            await self.flush(aseco, force_now=True)
            return

        if cmd == "specs":
            if len(args) < 2:
                await _send_chat(aseco, login, f'CP Live spectators are now {"shown" if SHOW_SPECTATORS else "hidden"}')
                return
            _toggle_config("SHOW_SPECTATORS")
            self.request_slice_refresh()
            await _send_chat_global(aseco, f'CP Live spectators are now {"shown" if SHOW_SPECTATORS else "hidden"}')
            await self.flush(aseco, force_now=True)
            return

        if cmd == "specmarker":
            if len(args) < 2:
                await _send_chat(aseco, login, f'CP Live spectator eye icon is {"enabled" if USE_SPECTATOR_ICON else "disabled"}')
                return
            _toggle_config("USE_SPECTATOR_ICON")
            self.request_row_refresh()
            await _send_chat_global(aseco, f'CP Live spectator eye icon has been {"enabled" if USE_SPECTATOR_ICON else "disabled"}')
            await self.flush(aseco, force_now=True)
            return

        if cmd == "spectarget":
            if len(args) < 2:
                await _send_chat(aseco, login, f'CP Live spectator targets are {"shown" if SHOW_SPECTATOR_TARGETS else "hidden"}')
                return
            _toggle_config("SHOW_SPECTATOR_TARGETS")
            self.request_row_refresh()
            await _send_chat_global(aseco, f'CP Live spectator targets are now {"shown" if SHOW_SPECTATOR_TARGETS else "hidden"}')
            await self.flush(aseco, force_now=True)
            return

        if cmd == "stats":
            await self.display_stats(aseco, login)
            return

        await self.show_help_manialink(aseco, login)

    async def toggle_player_ui_flag(self, aseco: "Aseco", login: str, key: str):
        if login not in self.players:
            return
        self.stats.local_toggles += 1
        current = getattr(self.players[login], key)
        setattr(self.players[login], key, not current)
        self.request_local_refresh(login)
        await self.flush(aseco)

    async def show_help_manialink(self, aseco: "Aseco", login: str):
        header = f"{{#black}}CP Live v{VERSION}$g overview:"
        help_rows = [
            ["$sUser commands:", "", ""],
            ["color", "", "Toggle between colored and plain nicknames"],
            ["toggle", "{#black}" + KEYS[TOGGLE_KEY], "Collapse or expand the Checkpoints Live widget"],
            [],
            ["$sMasterAdmin commands:", "", ""],
            ["refresh", "{#black}[<int>]", "Minimum global widget update interval (ms)"],
            ["rows", "{#black}[<int>]", "Maximum number of players shown"],
            ["strict", "{#black}[toggle]", "Strict throttling: enforce per-player rate limit"],
            ["leader", "{#black}[toggle]", "Track checkpoint differences to leading driver"],
            ["specs", "{#black}[toggle]", "Include spectators in shown players"],
            ["specmarker", "{#black}[toggle]", "Spectator symbol style"],
            ["spectarget", "{#black}[toggle]", "Display nicknames of spectator targets"],
            ["(enable|disable)", "", "Stop and resume all plugin execution"],
            [],
            ["$sNerd commands:", "", ""],
            ["stats", "", "View performance stats (per widget lifetime)"],
        ]
        display_manialink(
            aseco,
            login,
            header,
            ["Icons64x64_1", "TrackInfo", -0.01],
            help_rows,
            [1.4, 0.38, 0.17, 0.85],
            "OK",
        )

    async def display_stats(self, aseco: "Aseco", login: str):
        elapsed_ms = self.stats.current_widget_lifetime()
        elapsed_sec = max(elapsed_ms / 1000.0, 0.001)
        call_rate = round(self.stats.total_add_calls / elapsed_sec, 2)
        call_rate_no_csl = round(self.stats.total_add_calls_no_csl / elapsed_sec, 2)

        header = f"{{#black}}CP Live v{VERSION}$g event statistics per widget lifetime:"
        out = [
            ["{#black}Widget lifetime", _format_time(elapsed_ms)],
            [],
            ["$sTotal stats:", ""],
            ["{#black}Flushes", f"{self.stats.total_flushes}  (forced: {self.stats.forced_flushes}, empty: {self.stats.empty_flushes})"],
            ["{#black}addCalls", f"{self.stats.total_add_calls} ({call_rate}/s), no-CSL: {self.stats.total_add_calls_no_csl} ({call_rate_no_csl}/s, {self.stats.total_bundled} bundled)"],
            ["{#black}XML payloads", f'{round(self.stats.total_xml_bytes / (1024*1024), 2)} MiB, no-CSL: {round(self.stats.total_xml_bytes_no_csl / (1024*1024), 2)} MiB'],
            ["{#black}Spectator clicks", str(self.stats.target_forces)],
            ["{#black}Hash hits", f"SENTHASH={self.stats.hash_hits}   LISTHASHBIN={self.stats.row_model_hash_hits}"],
            ["{#black}Events (players)", f"CP={self.stats.checkpoints}   FIN={self.stats.finishes}   CONN={self.stats.connects}   DISC={self.stats.disconnects}"],
            ["{#black}Events (spectators)", f"MODE={self.stats.spec_changes}   TARGET={self.stats.target_changes}"],
            ["{#black}Config touches", f"LOCAL={self.stats.local_toggles}   GLOBAL={self.stats.config_changes}"],
            [],
            ["$saddCall stats by variant:", "$sreal / no-CSL (bundled)"],
        ]

        for key, count in self.stats.add_calls_by_variant.items():
            label = self.stats.variant_label(key)
            n = self.stats.add_calls_no_csl_by_variant.get(key, 0)
            p = self.stats.bundled_by_variant.get(key, 0)
            if key == "mixed":
                out.append(["{#black}" + label, str(count)])
            else:
                out.append(["{#black}" + label, f"{count} / {n} ({p})"])

        display_manialink(
            aseco,
            login,
            header,
            ["Icons64x64_1", "TrackInfo", -0.01],
            out,
            [1.4, 0.42, 0.98],
            "OK",
        )


# ---------------------------------------------------------------------------
# Global plugin object
# ---------------------------------------------------------------------------

_plugin: _CPLive | _DisabledCPLive = _CPLive()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ms() -> int:
    return int(time.time() * 1000)

def zlib_crc32(value: str) -> int:
    import zlib
    return zlib.crc32((value or "").encode("utf-8")) & 0xFFFFFFFF

def _parse_command_params(params: str) -> list[str]:
    params = (params or "").strip().lower()
    if not params:
        return [""]
    return params.split(None, 1)

def _strip_sizes_php(nick: str) -> str:
    """
    Port of PHP stripSizes():
    - preserve all color codes
    - remove only $n, $w, $o, $i (case-insensitive)
    - preserve escaped $$ correctly
    """
    import re

    nick = str(nick or "")
    placeholder = "\x00"

    nick = nick.replace("$$", placeholder)
    nick = re.sub(r"\$(?:[nwoi]|$)", "", nick, flags=re.IGNORECASE)
    nick = nick.replace(placeholder, "$$")

    return nick

def _format_time(milliseconds: int, is_delta: bool = False) -> str:
    prefix = ""
    ms = int(milliseconds or 0)
    if is_delta:
        if ms < 0:
            prefix = "$" + COLORS["DeltaNeg"] + "-"
        elif ms > 0:
            prefix = "$" + COLORS["DeltaPos"] + "+"
        else:
            prefix = "$" + COLORS["DeltaNeg"]
        ms = abs(ms)

    total_seconds = ms // 1000
    cs = (ms % 1000) // 10
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60

    if h > 0:
        return f"{prefix}{h}:{m:02d}:{s:02d}.{cs:02d}"
    if m > 0:
        return f"{prefix}{m}:{s:02d}.{cs:02d}"
    return f"{prefix}{s:02d}.{cs:02d}"

async def _send_chat(aseco: "Aseco", login: str, msg: str):
    await aseco.client.query_ignore_result(
        "ChatSendServerMessageToLogin",
        "$ff0> $fff" + aseco.format_colors(msg),
        login,
    )

async def _send_chat_global(aseco: "Aseco", msg: str):
    await aseco.client.query_ignore_result(
        "ChatSendServerMessage",
        "$ff0>> $fff" + aseco.format_colors(msg),
    )

async def _send_ml_logins(aseco: "Aseco", logins: str, xml: str, timeout: int = 0, hide: bool = False):
    await aseco.client.query_ignore_result(
        "SendDisplayManialinkPageToLogin",
        logins,
        xml,
        timeout,
        hide,
    )

async def _send_ml_global(aseco: "Aseco", xml: str, timeout: int = 0, hide: bool = False):
    await aseco.client.query_ignore_result(
        "SendDisplayManialinkPage",
        xml,
        timeout,
        hide,
    )

def _is_masteradmin(aseco: "Aseco", login: str) -> bool:
    try:
        return bool(aseco.isMasterAdminL(login))
    except Exception:
        pass
    try:
        vals = getattr(aseco.settings, "masteradmin_list", {}).get("TMLOGIN", [])
        return any(str(v).strip().lower() == str(login).strip().lower() for v in vals)
    except Exception:
        return False

def _set_config(name: str, value: Any) -> bool:
    global MAX_DISPLAY_ROWS, POS_X, POS_Y
    global WIDGET_UPDATE_INTERVAL, MIN_WIDGET_UPDATE_INTERVAL, STRICT_MODE, LEADER_MODE
    global ALLOW_NICK_STYLE_TOGGLE, PLAIN_NICKS, SHOW_SPECTATORS, USE_SPECTATOR_ICON, SHOW_SPECTATOR_TARGETS

    current = globals()[name]
    if current == value:
        return False
    globals()[name] = value
    if isinstance(_plugin, _CPLive):
        _plugin.stats.config_changes += 1
    return True

def _toggle_config(name: str) -> bool:
    return _set_config(name, not globals()[name])

async def _update_track_info(plugin: _CPLive, aseco: "Aseco"):
    try:
        info = await aseco.client.query("GetCurrentChallengeInfo") or {}
    except Exception:
        info = {}
    plugin.total_cps = int(info.get("NbCheckpoints", 0) or 0)
    plugin.challenge_seed = zlib_crc32(str(info.get("UId", "") or ""))
    changed = plugin.update_title_bar_xml()
    if changed and plugin.should_render:
        plugin.request_payload_refresh()

# ---------------------------------------------------------------------------
# Event wrappers
# ---------------------------------------------------------------------------

def register(aseco: "Aseco"):
    aseco.register_event("onSync", _on_sync)
    aseco.register_event("onEndRace", _on_end_race)
    aseco.register_event("onPlayerConnect", _on_player_connect)
    aseco.register_event("onCheckpoint", _on_checkpoint)
    aseco.register_event("onPlayerFinish", _on_player_finish)
    aseco.register_event("onPlayerManialinkPageAnswer", _on_manialink_answer)
    aseco.register_event("onPlayerInfoChanged", _on_player_info_changed)
    aseco.register_event("onRestartChallenge", _on_restart_challenge)
    aseco.register_event("onNewChallenge", _on_new_challenge)
    aseco.register_event("onBeginRound", _on_begin_round)
    aseco.register_event("onPlayerDisconnect", _on_player_disconnect)
    aseco.register_event("onEverySecond", _on_every_second)

    aseco.add_chat_command("cplive", 'Checkpoints Live v3: see "/cplive help"')
    aseco.register_event("onChat_cplive", chat_cplive)

async def _on_sync(aseco: "Aseco", _p=None):
    global _plugin
    if isinstance(_plugin, _DisabledCPLive):
        _plugin = _CPLive()
    await _plugin.init(aseco)

async def _on_end_race(aseco: "Aseco", _p=None):
    await _plugin.destroy_widget_ui(aseco)

async def _on_player_connect(aseco: "Aseco", player: "Player"):
    if not isinstance(_plugin, _CPLive):
        return

    _plugin.stats.connects += 1
    _plugin.init_player(player)
    await _plugin.sync_spectator_state(aseco, player.login, player)
    
    _plugin.payload_cache = {}
    
    _plugin.request_slice_refresh()
    _plugin.request_local_refresh(player.login, force_now=True)
    await _plugin.flush(aseco)

async def _on_player_disconnect(aseco: "Aseco", player: "Player"):
    if not isinstance(_plugin, _CPLive):
        return
    _plugin.stats.disconnects += 1
    login = player.login
    p = _plugin.players.pop(login, None)
    if p:
        _plugin.spec_action_to_login.pop(p.SpectateAction, None)
        _plugin.pid_to_login.pop(p.Pid, None)
    _plugin.payload_cache = {}
    _plugin.request_slice_refresh()
    await _plugin.flush(aseco, force_now=True)

async def _on_checkpoint(aseco: "Aseco", checkpoint: list):
    if not isinstance(_plugin, _CPLive):
        return
    if len(checkpoint) < 5:
        return

    _plugin.stats.checkpoints += 1
    login = checkpoint[1]
    if login not in _plugin.players:
        return

    cp_idx = int(checkpoint[4]) + 1
    cp_time = int(checkpoint[2])

    p = _plugin.players[login]
    p.CPNumber = cp_idx
    p.RawTime = cp_time

    while len(p.CPTimes) <= cp_idx:
        p.CPTimes.append(0)
    p.CPTimes[cp_idx] = cp_time

    _plugin.request_slice_refresh()
    await _plugin.flush(aseco)

async def _on_player_finish(aseco: "Aseco", finish):
    if not isinstance(_plugin, _CPLive):
        return

    _plugin.stats.finishes += 1
    login = getattr(getattr(finish, "player", None), "login", "")
    if not login or login not in _plugin.players:
        return

    if getattr(finish, "score", 0) == 0 or _plugin.players[login].CPNumber != _plugin.total_cps:
        _plugin.reset_player_time(login)

    _plugin.request_slice_refresh()
    await _plugin.flush(aseco)

async def _on_player_info_changed(aseco: "Aseco", player: "Player"):
    if not isinstance(_plugin, _CPLive):
        return

    login = getattr(player, "login", "")
    if not login or login not in _plugin.players:
        return

    state = _plugin.players[login]

    old_spec = bool(state.Spectator)
    old_target = int(state.SpectatesPid)
    old_auto = bool(state.AutoTarget)

    # Python receives a Player object; we call GetPlayerInfo to get the same data.
    # This is authoritative.
    await _plugin.sync_spectator_state(aseco, login, player)

    new_spec = bool(state.Spectator)
    new_target = int(state.SpectatesPid)
    new_auto = bool(state.AutoTarget)

    if old_spec != new_spec:
        _plugin.stats.spec_changes += 1
        _plugin.reset_player_time(login)

        _plugin.request_slice_refresh()
        _plugin.request_local_refresh(login, force_now=True)
        await _plugin.flush(aseco, force_now=True)
        return

    if not new_spec:
        # Driver with no spec transition — nothing to update in the widget
        return

    if SHOW_SPECTATORS and SHOW_SPECTATOR_TARGETS:
        if (old_target != new_target or old_auto != new_auto) and _plugin.is_login_possibly_shown(login):
            _plugin.stats.target_changes += 1
            _plugin.request_row_refresh()
            await _plugin.flush(aseco)

async def _on_manialink_answer(aseco: "Aseco", answer: list):
    if not isinstance(_plugin, _CPLive):
        return
    if len(answer) < 3:
        return

    login = answer[1]
    if login not in _plugin.players:
        return

    action = f"{int(answer[2]):08d}"
    if action == ANSWER_TOGGLE_HUD:
        await _plugin.toggle_player_ui_flag(aseco, login, "Collapsed")
        return

    if action == ANSWER_SWITCH_COLOR:
        await _plugin.toggle_player_ui_flag(aseco, login, "PlainNicks")
        return

    if action not in _plugin.spec_action_to_login or not _plugin.players[login].Spectator:
        return

    desired_target_login = _plugin.spec_action_to_login[action]
    if desired_target_login == login:
        return
    if desired_target_login not in _plugin.players:
        return
    if _plugin.players[desired_target_login].Spectator:
        return

    spectates_pid = _plugin.players[login].SpectatesPid
    current_target = _plugin.pid_to_login.get(spectates_pid, "")
    if desired_target_login == current_target:
        return

    _plugin.stats.target_forces += 1
    await aseco.client.query_ignore_result("ForceSpectatorTarget", login, desired_target_login, -1)

async def _on_restart_challenge(aseco: "Aseco", _challenge=None):
    if isinstance(_plugin, _CPLive):
        await _plugin.reset(aseco)

async def _on_new_challenge(aseco: "Aseco", _challenge=None):
    if isinstance(_plugin, _CPLive):
        await _update_track_info(_plugin, aseco)

async def _on_begin_round(aseco: "Aseco", _p=None):
    if isinstance(_plugin, _CPLive):
        await _plugin.reset(aseco)

async def _on_every_second(aseco: "Aseco", _p=None):
    if isinstance(_plugin, _CPLive):
        await _plugin.flush(aseco)

async def chat_cplive(aseco: "Aseco", command: dict):
    global _plugin

    login = command["author"].login
    args = _parse_command_params(command.get("params", ""))
    cmd = args[0]
    is_master_admin = _is_masteradmin(aseco, login)

    if cmd in ("disable", "enable"):
        if not is_master_admin:
            await _send_chat(aseco, login, "You don't have the required admin rights to do that!")
            return

        if cmd == "disable":
            if isinstance(_plugin, _CPLive):
                await _plugin.destroy_widget_ui(aseco)
                await _send_chat_global(aseco, "CP Live has been disabled")
                _plugin = _DisabledCPLive()
            else:
                await _send_chat(aseco, login, "CP Live is already disabled")
            return

        if cmd == "enable":
            if isinstance(_plugin, _DisabledCPLive):
                _plugin = _CPLive()
                await _plugin.init(aseco)
            else:
                await _send_chat(aseco, login, "CP Live is already enabled")
            return

    await _plugin.handle_chat(aseco, command)
