"""Bounded derived reads; canonical state and revision ownership stay in the domain."""

import json
import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any


class RevisionCache:
    def __init__(self, *, max_bytes: int, max_entries: int):
        self.max_bytes, self.max_entries = max_bytes, max_entries
        self._condition = threading.Condition()
        self._values: OrderedDict[Hashable, bytes] = OrderedDict()
        self._pending: set[Hashable] = set()
        self._bytes = 0

    def get(self, key: Hashable, load: Callable[[], Any]) -> Any:
        with self._condition:
            while key in self._pending:
                self._condition.wait()
            encoded = self._values.get(key)
            if encoded is not None:
                self._values.move_to_end(key)
            else:
                self._pending.add(key)
        if encoded is None:
            try:
                encoded = json.dumps(load(), ensure_ascii=False, separators=(",", ":")).encode()
                with self._condition:
                    if len(encoded) <= self.max_bytes:
                        while self._values and (
                            len(self._values) >= self.max_entries
                            or self._bytes + len(encoded) > self.max_bytes
                        ):
                            _, removed = self._values.popitem(last=False)
                            self._bytes -= len(removed)
                        self._values[key] = encoded
                        self._bytes += len(encoded)
            finally:
                with self._condition:
                    self._pending.remove(key)
                    self._condition.notify_all()
        # Callers enrich metrics and view objects. Never lend a cached mutable object.
        return json.loads(encoded)
