"""Bounded repeat-trace suppression. Each handler owns its own filter."""

import logging
import time
from collections import OrderedDict


class RepeatTraceFilter(logging.Filter):
    def __init__(self):
        super().__init__()
        self._seen = OrderedDict()

    def filter(self, record):
        record.repeat_summary = ''
        if not record.exc_info:
            return True
        key = record.name, record.levelno, str(record.msg), record.exc_info[0]
        now = time.monotonic()
        previous = self._seen.get(key)
        if previous and now - previous[0] < 60:
            self._seen[key] = previous[0], previous[1] + 1
            return False
        if previous and previous[1]:
            record.repeat_summary = ' [suppressed ' + str(previous[1]) + ' repeated traces]'
        self._seen[key] = now, 0
        self._seen.move_to_end(key)
        while len(self._seen) > 512:
            self._seen.popitem(last=False)
        return True
