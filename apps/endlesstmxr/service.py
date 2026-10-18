from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

from pyxaseco.app_services import get_dedi_db, get_tmx_service
from pyxaseco.core.config import display_path
from pyxaseco.models import Gameinfo

if TYPE_CHECKING:
    from pyxaseco.core.aseco import Aseco


logger = logging.getLogger(__name__)

ENABLED = True
TRIGGER = 'author'
SECTIONS: list[str] = []
IGNORED_STYLES: list[str] = ['RPG', 'Trial']
LEGACY_ALLOWED_STYLES: list[str] = []
ANNOUNCE = True
AUTO_ERASE_SKIPPED_MAP = False
MAX_AUTHOR_TIME_SECONDS = 120

_runtime_aseco = None
_triggered_uid = ''
_busy = False
_pending = None
_erase_after_transition = None

VALID_TRIGGERS = {'author', 'tmx_wr', 'dedimania_wr', 'disabled'}
_ALL_STYLE_NAMES = {
    'Normal', 'Stunt', 'Maze', 'Offroad', 'Laps', 'Fullspeed',
    'LOL', 'Tech', 'SpeedTech', 'RPG', 'PressForward', 'Trial', 'Grass',
}


def register(aseco: 'Aseco') -> None:
    global _runtime_aseco
    _runtime_aseco = aseco
    _load_config(aseco)
    aseco.register_event('onNewChallenge', _on_new_challenge)
    aseco.register_event('onRestartChallenge', _on_new_challenge)
    aseco.register_event('onPlayerFinish1', _on_player_finish)


def _normalise_sections(raw_sections) -> list[str]:
    allowed = {'TMNF', 'TMU', 'TMN', 'TMO', 'TMS'}
    values = raw_sections if isinstance(raw_sections, (list, tuple)) else [raw_sections]
    sections: list[str] = []
    for value in values:
        item = str(value or '').strip().upper()
        if item in allowed and item not in sections:
            sections.append(item)
    return sections


def _normalise_styles(raw_styles) -> list[str]:
    values = raw_styles if isinstance(raw_styles, (list, tuple)) else [raw_styles]
    styles: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or '').strip()
        if not item:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        styles.append(item)
    return styles


def _load_config(aseco: 'Aseco') -> None:
    global ENABLED, TRIGGER, SECTIONS, IGNORED_STYLES, LEGACY_ALLOWED_STYLES, ANNOUNCE, AUTO_ERASE_SKIPPED_MAP, MAX_AUTHOR_TIME_SECONDS
    ENABLED = True
    TRIGGER = 'author'
    SECTIONS = []
    IGNORED_STYLES = ['RPG', 'Trial']
    LEGACY_ALLOWED_STYLES = []
    ANNOUNCE = True
    AUTO_ERASE_SKIPPED_MAP = False
    MAX_AUTHOR_TIME_SECONDS = 120

    try:
        from pyxaseco.settings_loader import overlay_app_defaults
        overlay_app_defaults(
            'endlesstmxr',
            sys.modules[__name__],
            attr_map={
                'enabled': 'ENABLED',
                'trigger': 'TRIGGER',
                'sections': 'SECTIONS',
                'ignored_styles': 'IGNORED_STYLES',
                'announce': 'ANNOUNCE',
                'auto_erase_skipped_map': 'AUTO_ERASE_SKIPPED_MAP',
                'max_author_time_seconds': 'MAX_AUTHOR_TIME_SECONDS',
            },
            base_dir=getattr(aseco, '_base_dir', None),
        )
        overlay_app_defaults(
            'endlesstmxr',
            sys.modules[__name__],
            attr_map={
                'allowed_styles': 'LEGACY_ALLOWED_STYLES',
            },
            base_dir=getattr(aseco, '_base_dir', None),
        )
    except Exception:
        pass

    TRIGGER = str(TRIGGER or 'author').strip().lower()
    if TRIGGER not in VALID_TRIGGERS:
        TRIGGER = 'author'
    if not ENABLED:
        TRIGGER = 'disabled'

    SECTIONS = _normalise_sections(SECTIONS)
    IGNORED_STYLES = _normalise_styles(IGNORED_STYLES)
    LEGACY_ALLOWED_STYLES = _normalise_styles(LEGACY_ALLOWED_STYLES)
    if LEGACY_ALLOWED_STYLES and not IGNORED_STYLES:
        allowed_lookup = {item.casefold() for item in LEGACY_ALLOWED_STYLES}
        IGNORED_STYLES = [style for style in sorted(_ALL_STYLE_NAMES) if style.casefold() not in allowed_lookup]

    path = getattr(aseco, '_base_dir', None)
    if path:
        logger.info(
            '[EndlessTMXR] Config loaded from %s (trigger=%s)',
            display_path(path / 'apps' / 'endlesstmxr' / 'app_defaults.toml'),
            TRIGGER,
        )


async def reload_runtime(aseco: 'Aseco') -> None:
    global _triggered_uid, _busy, _pending, _erase_after_transition
    _load_config(aseco)
    _triggered_uid = ''
    _busy = False
    _pending = None
    _erase_after_transition = None
    aseco.jobs.service('endless_target').invalidate()


def get_random_candidate_filters() -> dict[str, object]:
    return {
        'sections': list(SECTIONS),
        'ignored_styles': list(IGNORED_STYLES),
        'max_author_time_seconds': int(MAX_AUTHOR_TIME_SECONDS or 0),
    }


async def _on_new_challenge(_aseco: 'Aseco', challenge) -> None:
    global _triggered_uid, _busy, _pending, _erase_after_transition
    erase = _erase_after_transition
    _pending = None
    _erase_after_transition = None
    _triggered_uid = ''
    _busy = False
    if challenge is None:
        return
    if (erase and _is_skip_enabled_for_runtime(_aseco) and
            str(getattr(challenge, 'uid', '')) == erase['next_uid'] and
            erase['old_map']['uid'] != erase['next_uid']):
        from types import SimpleNamespace
        if await _erase_current_map(_aseco, SimpleNamespace(**erase['old_map'])):
            from pyxaseco.helpers import format_text
            await _aseco.client.query_ignore_result(
                'ChatSendServerMessage', _aseco.format_colors(format_text(
                    '{#server}>> {#admin}Auto-removed skipped map: {#highlite}{1}',
                    erase['old_map']['name'],
                )),
            )





def _trigger_label(trigger: str) -> str:
    labels = {
        'author': 'author time',
        'tmx_wr': 'TMX WR',
        'dedimania_wr': 'Dedimania WR',
        'disabled': 'disabled',
    }
    return labels.get(str(trigger or '').strip().lower(), 'target')


async def _resolve_trigger_target(aseco: 'Aseco', challenge, trigger=None) -> tuple[int, str]:
    trigger = str(trigger if trigger is not None else TRIGGER).lower()
    author = int(getattr(challenge, 'authortime', 0) or 0)
    if trigger == 'author':
        return author, _trigger_label(trigger)
    if trigger == 'tmx_wr':
        from apps.tmx.service import get_tmx_world_record_for_uid
        # Exceptions mean unavailable, not "no WR". Only a confirmed empty
        # replay list permits author fallback.
        data = await get_tmx_world_record_for_uid(aseco, challenge.uid)
        score = int(data.get('score', 0) or 0)
        return (score, _trigger_label(trigger)) if score > 0 else (author, _trigger_label('author'))
    if trigger == 'dedimania_wr':
        if not getattr(challenge, 'dedi_valid', False):
            raise RuntimeError('Dedimania records not loaded')
        score = int(getattr(challenge, 'dedi_score', 0) or 0)
        return (score, _trigger_label(trigger)) if score > 0 else (author, _trigger_label('author'))
    return 0, _trigger_label(trigger)


async def _erase_current_map(aseco: 'Aseco', challenge) -> bool:
    fname = str(getattr(challenge, 'filename', '') or '').strip()
    uid = str(getattr(challenge, 'uid', '') or '').strip()
    if not fname:
        return False

    try:
        from apps.admin import command_router as admin_chat

        await admin_chat._remove_track_from_rotation(aseco, fname, uid)
        await admin_chat._erase_track_from_localdb(aseco, uid)
        try:
            gbx_path = admin_chat._resolve_track_path(aseco, fname)
            if gbx_path.exists():
                gbx_path.unlink()
        except Exception as exc:
            aseco.console('[EndlessTMXR] erase file warning: {1}', str(exc))
        return True
    except Exception as exc:
        logger.warning('[EndlessTMXR] Could not auto-erase skipped map %s: %s', uid or fname, exc)
        return False


def _is_enabled_for_runtime(aseco: 'Aseco') -> bool:
    try:
        active = set(getattr(aseco, 'active_apps', []) or [])
    except Exception:
        active = set()
    return 'endlesstmxr' in active and ENABLED and TRIGGER != 'disabled'


def _is_skip_enabled_for_runtime(aseco: 'Aseco') -> bool:
    try:
        active = set(getattr(aseco, 'active_apps', []) or [])
    except Exception:
        active = set()
    return 'endlesstmxr' in active and ENABLED


def _current_map_allowed(challenge) -> bool:
    author_time_ms = int(getattr(challenge, 'authortime', 0) or 0)
    if int(MAX_AUTHOR_TIME_SECONDS or 0) > 0 and author_time_ms > int(MAX_AUTHOR_TIME_SECONDS) * 1000:
        return False
    return True


async def request_skip(aseco: 'Aseco', *, login='', nickname='Skip', complete=None,
                       automatic=False, target_label='target') -> bool:
    """Return handled, not committed: keep playing until preparation completes."""
    global _pending, _busy, _triggered_uid, _erase_after_transition
    if not _is_skip_enabled_for_runtime(aseco):
        return False
    if _pending is not None:
        return True
    from pyxaseco.core.background_jobs import Admission
    from apps.jukebox.tmx_jobs import get_tmx_jobs
    challenge = aseco.server.challenge
    context = aseco.capture_job_context()
    old_map = {key: getattr(challenge, key, '') for key in ('uid', 'filename', 'name')}
    pending = {'context': context, 'old_map': old_map}
    _pending, _busy = pending, True
    erase = bool(AUTO_ERASE_SKIPPED_MAP)
    announce = bool(ANNOUNCE)

    async def discard():
        global _pending, _busy
        if _pending is pending:
            _pending, _busy = None, False

    async def guard():
        if _pending is not pending or not _is_skip_enabled_for_runtime(aseco):
            return False
        now = aseco.capture_job_context()
        if now != context:
            return False
        info = await aseco.client.query('GetCurrentChallengeInfo')
        return str(info.get('UId', '') or info.get('Uid', '')) == old_map['uid']

    async def applied(ok, info):
        global _erase_after_transition, _triggered_uid
        try:
            if not ok:
                logger.warning('[EndlessTMXR] Replacement preparation failed; current map kept running')
                if login:
                    from apps.jukebox.backend import _reply
                    await _reply(aseco, login, '{#server}> {#error}Replacement failed; map kept running. Retry skip.')
                return
            from apps.jukebox import backend as b
            uid = str(info.get('uid', '') or '')
            if not uid or not await guard():
                b.jukebox.pop(uid, None)
                return
            if not await b.force_jukebox_track_next(aseco, uid) or not await guard():
                b.jukebox.pop(uid, None)
                if login:
                    await _reply(aseco, login, '{#server}> {#error}Could not activate replacement; map kept running.')
                return
            accepted = await aseco.client.query('NextChallenge')
            if accepted is not True:
                b.jukebox.pop(uid, None)
                logger.warning('[EndlessTMXR] NextChallenge was not acknowledged; no erase scheduled')
                if login:
                    await _reply(aseco, login, '{#server}> {#error}Skip was not acknowledged; retry skip.')
                return
            _triggered_uid = old_map['uid']
            if erase:
                _erase_after_transition = {'old_map': old_map, 'next_uid': uid}
            if complete is not None:
                await complete()
            elif automatic and announce:
                from pyxaseco.helpers import format_text
                message = format_text(
                    '{#server}>> {#highlite}{1}$z$s {#admin}beats {#highlite}{2} '
                    '{#admin}and triggers EndlessTMXR: {#highlite}{3} {#admin}will be next!',
                    nickname, target_label, info.get('name', uid),
                )
                await aseco.client.query_ignore_result('ChatSendServerMessage', aseco.format_colors(message))
        finally:
            await discard()

    try:
        filters = get_random_candidate_filters()
        if not filters['sections']:
            filters['sections'] = ['TMNF', 'TMN']
        outcome = await get_tmx_jobs(aseco).request(
            login=login, nickname=nickname, complete=applied, random_filters=filters,
            current_map=True, guard=guard, discarded=discard,
            acknowledge=not automatic,
        )
        if outcome != Admission.ACCEPTED:
            await discard()
    except Exception as error:
        await discard()
        logger.warning('[EndlessTMXR] Could not admit replacement (%s)', type(error).__name__)
    return True





async def _on_player_finish(aseco: 'Aseco', finish_item) -> None:
    if not _is_enabled_for_runtime(aseco) or _busy or getattr(aseco, 'warmup_phase', False):
        return
    challenge = aseco.server.challenge
    uid = str(getattr(challenge, 'uid', '') or '')
    score = int(getattr(finish_item, 'score', 0) or 0)
    if not uid or uid == _triggered_uid or score <= 0 or not _current_map_allowed(challenge):
        return
    player = getattr(finish_item, 'player', None)
    login = str(getattr(player, 'login', '') or '')
    nickname = str(getattr(player, 'nickname', '') or login)
    mode = int(getattr(aseco.server.gameinfo, 'mode', -1))
    from types import SimpleNamespace
    from pyxaseco.core.background_jobs import JobEnvelope, JobPolicy
    snapshot = {key: getattr(challenge, key, '') for key in ('uid', 'authortime', 'tmx_id', 'tmx_prefix')}
    dedi = get_dedi_db(aseco)
    records = dedi.get('Challenge', {}).get('Records', [])
    snapshot['dedi_valid'] = bool(dedi.get('RecsValid'))
    snapshot['dedi_score'] = int(records[0].get('Best', records[0].get('Time', 0)) or 0) if records else 0
    trigger = TRIGGER
    envelope = JobEnvelope.capture(aseco.capture_job_context(login=login, nickname=nickname),
                                   {'challenge': snapshot, 'score': score, 'mode': mode})
    async def operation(job):
        return await _resolve_trigger_target(aseco, SimpleNamespace(**job.payload()['challenge']), trigger)
    async def apply(result):
        if not _is_enabled_for_runtime(aseco) or TRIGGER != trigger:
            return
        if result.status != 'completed':
            logger.warning('[EndlessTMXR] Target lookup unavailable; no author fallback on network failure')
            return
        target, label = result.value
        beat = score >= target if mode == Gameinfo.STNT else score <= target
        if target > 0 and beat and not _busy:
            await request_skip(aseco, login=login, nickname=nickname, automatic=True, target_label=label)
    aseco.jobs.service('endless_target', JobPolicy(capacity=32)).submit(
        envelope, operation, apply, dedupe_key=login + ':' + str(score),
    )
