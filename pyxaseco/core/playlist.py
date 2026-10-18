"""Controller-lane playlist snapshot with explicit invalidation."""

from __future__ import annotations
import time


class Playlist:
    def __init__(self, aseco):
        self.aseco = aseco
        self._rows = None
        self._loaded_at = 0.0
        self.revision = 0
        self.by_uid, self.by_filename = {}, {}
        aseco.register_event('onTracklistChanged', self.invalidate)
        aseco.register_event('onChallengeListModified', self.invalidate)

    async def invalidate(self, _aseco, _param=None):
        self.revision += 1
        self._rows = None
        self.by_uid, self.by_filename = {}, {}

    async def snapshot(self, *, refresh=False):
        if refresh or self._rows is None or time.monotonic() - self._loaded_at >= 60:
            rows, offset = [], 0
            while True:
                batch = await self.aseco.client.query('GetChallengeList', 500, offset)
                if not isinstance(batch, list):
                    raise RuntimeError('Invalid playlist response')
                rows.extend(dict(row) for row in batch)
                if len(batch) < 500:
                    break
                offset += len(batch)
            if self._rows is not None and self._rows != rows:
                self.revision += 1
            self._rows = rows
            self._loaded_at = time.monotonic()
            self.by_uid = {row.get('UId', row.get('Uid', '')): row for row in rows}
            self.by_filename = {row.get('FileName', ''): row for row in rows}
        return [dict(row) for row in self._rows]


def playlist(aseco):
    service = aseco.services.get('playlist')
    if service is None:
        service = Playlist(aseco)
        aseco.services.register('playlist', service, owner='core')
    return service
