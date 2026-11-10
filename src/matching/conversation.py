"""Bounded in-memory conversation state for a single local process."""
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from uuid import UUID

from .models import Mode, ParsedPreferences, Recommendation


@dataclass(frozen=True)
class Session:
    preferences: ParsedPreferences
    results: tuple[Recommendation, ...]
    mode: Mode


class Sessions:
    def __init__(self, ttl=1800, capacity=512):
        self._ttl = ttl
        self._capacity = capacity
        self._entries: OrderedDict[UUID, tuple[float, Session]] = OrderedDict()
        self._lock = Lock()

    def get(self, session_id):
        with self._lock:
            entry = self._entries.get(session_id)
            if not entry:
                return None
            when, value = entry
            if monotonic() - when >= self._ttl:
                self._entries.pop(session_id, None)
                return None
            return value

    def put(self, session_id, value):
        with self._lock:
            now = monotonic()
            self._entries.pop(session_id, None)
            self._entries[session_id] = (now, value)
            while self._entries:
                when, _ = next(iter(self._entries.values()))
                if len(self._entries) <= self._capacity and now - when < self._ttl:
                    break
                self._entries.popitem(last=False)

