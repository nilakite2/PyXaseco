"""Small expiring LRU caches; failures are never inserted as absence."""

from collections import OrderedDict
import time


class BoundedCache:
    def __init__(self, capacity=512, ttl=600, negative_ttl=30):
        self.capacity, self.ttl, self.negative_ttl = capacity, ttl, negative_ttl
        self._items = OrderedDict()

    def get(self, key, default=None):
        item = self._items.get(key)
        if item is None:
            return default
        expires, value = item
        if expires <= time.monotonic():
            del self._items[key]
            return default
        self._items.move_to_end(key)
        return value

    def __setitem__(self, key, value):
        ttl = self.ttl if value else self.negative_ttl
        self._items[key] = time.monotonic() + ttl, value
        self._items.move_to_end(key)
        while len(self._items) > self.capacity:
            self._items.popitem(last=False)

    def clear(self):
        self._items.clear()
