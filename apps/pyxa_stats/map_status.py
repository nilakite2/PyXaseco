"""Small rotation snapshots; no dependency on UI or optional timer apps."""

import logging
import sys
from time import monotonic

from pyxaseco.helpers import strip_colors

logger = logging.getLogger(__name__)


def map_payload(challenge):
    def read(*keys):
        for key in keys:
            value = challenge.get(key) if isinstance(challenge, dict) else getattr(challenge, key, None)
            if value:
                return str(value).strip()
        return ''
    uid = read('uid', 'UId', 'Uid')
    if not uid:
        return None
    raw = read('name', 'Name')
    return {'uid': uid, 'name': strip_colors(raw) or uid, 'name_raw': raw,
            'author': strip_colors(read('author', 'Author')),
            'environment': read('environment', 'Environment', 'Environnement', 'Env')}


class MapStatus:
    def __init__(self):
        self.previous = None
        self.current = None
        self.next = None
        self.dirty = True
        self._timer = None
        self._timer_marker = None
        self._sampled_at = 0
        self.queued = []

    def observe(self, aseco):
        current = map_payload(getattr(aseco.server, 'challenge', None))
        if current != self.current:
            self.dirty = True
        if current and self.current and current['uid'] != self.current['uid']:
            self.previous = self.current
            self.next = None
        self.current = current

    def sample_timer(self, aseco):
        raw = None
        if 'flexitime' in getattr(aseco, 'active_apps', ()):
            service = aseco.services.get('service/flexitime')
            if service:
                raw = service.public_status()
        if raw and (not self.current or raw.get('map_uid') != self.current['uid']):
            raw = None
        marker = None
        if raw:
            total = max(1, raw['initial_seconds'])
            # Buckets change at 75%, 50%, 25% and zero; no per-second publishing.
            quarter = (raw['remaining_seconds'] * 4 - 1) // total
            marker = (raw['map_uid'], raw['revision'], raw['paused'], raw['phase'], quarter)
        if marker != self._timer_marker:
            self._timer_marker = marker
            self._timer = dict(raw) if raw else None
            self._sampled_at = monotonic()
            self.dirty = True

    async def refresh(self, aseco):
        self.observe(aseco)
        uid = self.current['uid'] if self.current else None
        self.queued = []
        module = sys.modules.get('apps.jukebox.jukebox')
        if 'jukebox' in getattr(aseco, 'active_apps', ()) and module:
            queue = module.get_jukebox()
            if isinstance(queue, dict) and queue:
                self.queued = [item for key, value in list(queue.items())[:200]
                               if (item := map_payload({**value, 'uid': value.get('uid') or key}))]
        try:
            next_map = self.queued[0] if self.queued else map_payload(await aseco.client.query('GetNextChallengeInfo'))
        except Exception as exc:
            logger.debug('[PYXA Stats] Next map unavailable: %s', exc)
            next_map = None
        current = map_payload(getattr(aseco.server, 'challenge', None))
        if (current['uid'] if current else None) == uid:
            self.next = next_map
        else:
            self.observe(aseco)

    def payload(self, aseco, refresh_seconds):
        self.observe(aseco)
        timer = ({**self._timer, 'sample_age_seconds': max(0, int(monotonic() - self._sampled_at))}
                 if self._timer else None)
        return {'previous_map': self.previous, 'current_map': self.current,
                'next_map': self.next, 'timer': timer, 'refresh_seconds': refresh_seconds}
