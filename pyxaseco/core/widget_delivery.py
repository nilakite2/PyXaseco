"""Confirmed persistent widget delivery, grouped by identical recipient views."""

from __future__ import annotations

import re
from collections import OrderedDict
from hashlib import sha256

from .gbx_client import GbxError


def is_score_phase(aseco):
    """Race phase is separate from the configured game mode (Rounds/TA/etc.)."""
    phase = getattr(aseco, 'score_phase', None)
    if phase is not None:
        return bool(phase)
    return (getattr(aseco, 'currstatus', None) == 5 or
            getattr(getattr(aseco.server, 'gameinfo', None), 'mode', -1) == 7)


class WidgetDelivery:
    def __init__(self, aseco):
        self.aseco = aseco
        self._sent = OrderedDict()

    def invalidate(self, login=None):
        if login is None:
            self._sent.clear()
        else:
            for key in list(self._sent):
                if key[0] == login:
                    del self._sent[key]

    def page_digest(self, login, page):
        return self._sent.get((login, str(page)))

    def invalidate_page(self, login, page):
        self._sent.pop((login, str(page)), None)

    async def send(self, method, *args):
        service = _presentation_service(self.aseco)
        groups = service.delivery_groups(method, *args) if service else None
        result = None
        for group_method, group_args in groups or [(method, args)]:
            result = await self._send(group_method, *group_args)
        if service:
            service.remember_ui(method, *args)
        return result

    async def _send(self, method, *args):
        if method == 'SendDisplayManialinkPageToLogin':
            login, xml, lifetime, hide = args
            recipients = login.split(',')
        else:
            xml, lifetime, hide = args
            recipients = [p.login for p in self.aseco.server.players.all()]
        # Timed/modal pages must preserve their original semantics.
        ids = re.findall(r'<manialink\s+[^>]*\bid=["\']([^"\']+)["\']', xml)
        if not ids or lifetime or hide:
            for login in recipients:
                if hide:
                    self.invalidate(login)
                else:
                    for page in ids:
                        self._sent.pop((login, page), None)
            return await self.aseco.client.query_ignore_result(method, *args)
        digest = sha256(xml.encode('utf-8')).digest()
        fragments = re.findall(r'<manialink\b[^>]*(?:/>|>.*?</manialink>)', xml, re.DOTALL)
        page_hashes = {page: sha256(fragment.encode('utf-8')).digest()
                       for page, fragment in zip(ids, fragments)}
        # custom_ui is outside page 0; it must participate in its cache key.
        if len(fragments) != len(ids) or '<custom_ui' in xml:
            page_hashes = dict.fromkeys(ids, digest)
        changed = [login for login in recipients
                   if any(self._sent.get((login, page)) != page_hashes[page] for page in ids)]
        if not changed:
            self.aseco.performance.increment('ui.delivery_skipped')
            return True
        # Keep recipient lists below the GBX request budget. Failed or
        # unacknowledged sends do not advance the last-delivered view.
        for offset in range(0, len(changed), 100):
            await self._send_group(changed[offset:offset + 100], xml, page_hashes)
        return True

    async def _send_group(self, group, xml, page_hashes):
        try:
            success = await self.aseco.client.query('SendDisplayManialinkPageToLogin',
                                                   ','.join(group), xml, 0, False)
        except GbxError as error:
            if error.code != -1000 or 'login unknown' not in error.message.lower():
                raise
            # A disconnect callback can still be queued when a grouped send arrives.
            # Split only the failed group, retaining batching for online recipients.
            if len(group) == 1:
                self.invalidate(group[0])
                return
            middle = len(group) // 2
            await self._send_group(group[:middle], xml, page_hashes)
            await self._send_group(group[middle:], xml, page_hashes)
            return
        if success is not True:
            raise RuntimeError('Widget delivery not acknowledged')
        for login in group:
            for page, digest in page_hashes.items():
                self._sent[(login, page)] = digest
                self._sent.move_to_end((login, page))
        while len(self._sent) > 16384:
            self._sent.popitem(last=False)
        self.aseco.performance.increment('ui.delivery_groups')


async def deliver_ui(aseco, method, *args):
    delivery = getattr(aseco, 'ui_delivery', None)
    if delivery is None:
        service = _presentation_service(aseco)
        groups = service.delivery_groups(method, *args) if service else None
        result = None
        for group_method, group_args in groups or [(method, args)]:
            result = await aseco.client.query_ignore_result(group_method, *group_args)
        if service:
            service.remember_ui(method, *args)
        return result
    return await delivery.send(method, *args)


def _presentation_service(aseco):
    lookup = getattr(aseco, 'get_service', None)
    service = lookup('ui/uistyle') if callable(lookup) else None
    return service if callable(getattr(service, 'delivery_groups', None)) else None
