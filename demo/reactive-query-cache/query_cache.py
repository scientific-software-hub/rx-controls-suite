"""Rx-backed app-level query cache — the headline of this demo.

Problem
-------
The suite's reactive primitives (``monitor_pv``, ``read_attribute``, …) are
**cold / unicast**: every ``.subscribe()`` opens its *own* upstream Channel
Access monitor or Tango network read.  In a multi-component UI, N panels that
each request the same PV = N independent upstream subscriptions; SCADA load
scales linearly with the component count.

Solution
--------
``QueryCache`` sits between the control-system primitives and the UI.
Each unique query key is backed by **exactly one** upstream polled stream.
All UI components observing the same key share that stream via a
``ReplaySubject(buffer_size=1)`` multicast bus — the standard RxPY building
block for "share + last-value cache".

Capabilities showcased
----------------------
* **Dedup**       N components watching key ``X`` → 1 upstream SCADA sub
* **replay(1)**   a newly-subscribing component gets the *cached last value*
                  immediately instead of waiting up to ``poll_ms`` for the
                  next tick  (mirrors TanStack Query's cached-data-on-mount)
* **stale_ms**    tag a value fresh/stale based on how old it is; visible in
                  the Cache-Inspector panel
* **gc_ms**       keep the upstream warm for ``gc_ms`` after the last
                  component unsubscribes, then tear it down via ref-count.
                  If a new component arrives inside the grace window it
                  reuses the still-warm upstream and gets the cached value.

None of this requires importing any external data-fetching library; the whole
cache is built from the RxPY operators already in the suite.

Usage::

    def source_factory(key: str) -> rx.Observable:
        # Return a cold polling Observable for this key.
        return rx.interval(timedelta(milliseconds=poll_ms), scheduler=scheduler).pipe(
            ops.flat_map(lambda _: read_attribute(device, key_to_attr[key])),
            ops.map(float),
        )

    cache = QueryCache(scheduler, source_factory,
                       poll_ms=1000, stale_ms=5_000, gc_ms=10_000)

    # Each component calls .observe() independently — the cache deduplicates.
    d = cache.observe("ring.current").subscribe(on_next=my_handler)
    ...
    d.dispose()   # decrements ref-count; gc timer arms if this was the last one
    cache.close()
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import reactivex as rx
from reactivex.subject import ReplaySubject

log = logging.getLogger(__name__)


# ── per-key state ──────────────────────────────────────────────────────────────

@dataclass
class _KeyEntry:
    """All mutable state for a single cache key."""
    key:               str
    subject:           ReplaySubject    # multicast bus; feeds every downstream observer
    observer_count:    int  = 0         # live component subscriptions to this key
    upstream_disp:     Any  = None      # Rx Disposable for the single upstream sub
    upstream_live:     bool = False     # is the upstream currently subscribed?
    last_value:        Any  = None      # most-recently received upstream value
    last_value_ts:     float = 0.0      # monotonic timestamp of last_value
    gc_handle:         Any  = None      # asyncio.TimerHandle — pending teardown
    upstream_sub_total: int = 0         # lifetime upstream subscribes (for tests/debug)


# ── the cache ──────────────────────────────────────────────────────────────────

class QueryCache:
    """
    App-level cache built entirely from the suite's own Rx primitives.

    Parameters
    ----------
    scheduler:
        The ``AsyncIOScheduler`` used by the FastAPI app's event loop.
    source_factory:
        Callable ``(key: str) -> rx.Observable`` that creates a *cold*
        upstream polling stream for the given query key.  Must be a
        pure factory — called at most once per key while the upstream is live.
    poll_ms:
        Interval between upstream reads (ms).  Used only for the ops/sec
        metric calculation.
    stale_ms:
        Age (ms) after which a cached value is tagged *stale* in metrics.
    gc_ms:
        Grace period (ms) before the upstream subscription is torn down
        after the last observer leaves.  A new observer arriving within
        the window reuses the warm upstream.
    """

    def __init__(
        self,
        scheduler,
        source_factory: Callable[[str], rx.Observable],
        *,
        poll_ms:  int = 1_000,
        stale_ms: int = 5_000,
        gc_ms:    int = 10_000,
    ):
        self._scheduler      = scheduler
        self._source_factory = source_factory
        self._poll_ms        = poll_ms
        self._stale_ms       = stale_ms
        self._gc_ms          = gc_ms
        self._entries: dict[str, _KeyEntry] = {}
        # active upstream subscriptions == unique warm keys:
        # this is the number that stays FLAT as component subs grow.
        self._active_upstream_subs: int = 0
        # acquire the running loop (must be called from inside an asyncio context)
        self._loop = asyncio.get_event_loop()

    # ── public API ─────────────────────────────────────────────────────────────

    def observe(self, key: str) -> rx.Observable:
        """Return a multicast, ref-counted, last-value-cached Observable for *key*.

        * The first subscriber causes the upstream to be connected (lazily).
        * Subsequent subscribers share the same upstream — no additional SCADA load.
        * A subscriber that arrives while the upstream is already warm gets the
          cached last value delivered synchronously via ``ReplaySubject``.
        * When the last subscriber disposes, a gc timer is armed; the upstream
          stays warm until it fires (``gc_ms``), then disconnects.
        * A new subscriber arriving inside the gc window cancels the teardown.
        """
        entry = self._get_or_create(key)

        def subscribe(observer, scheduler=None):
            # ── cancel any pending gc teardown ──
            if entry.gc_handle is not None:
                entry.gc_handle.cancel()
                entry.gc_handle = None
                log.debug("QueryCache [%s] gc cancelled — new observer arrived in grace window", key)

            entry.observer_count += 1

            # ── connect upstream on the first observer ──
            if not entry.upstream_live:
                self._connect_upstream(entry)

            # ── tap into the multicast bus ──
            # ReplaySubject(buffer_size=1) delivers the cached last value
            # synchronously to this new observer before returning.
            inner = entry.subject.subscribe(
                on_next=observer.on_next,
                on_error=observer.on_error,
                on_completed=observer.on_completed,
            )

            def dispose():
                inner.dispose()
                entry.observer_count = max(0, entry.observer_count - 1)
                if entry.observer_count == 0 and entry.upstream_live:
                    log.debug(
                        "QueryCache [%s] last observer gone — arming gc timer %.1f s",
                        key, self._gc_ms / 1000.0,
                    )
                    entry.gc_handle = self._loop.call_later(
                        self._gc_ms / 1000.0,
                        lambda: self._gc_teardown(entry),
                    )

            return dispose

        return rx.create(subscribe)

    def metrics(self) -> dict:
        """Snapshot of cache state — JSON-serialisable."""
        now = time.monotonic()
        keys: dict = {}
        total_observers = 0

        for key, entry in self._entries.items():
            if entry.last_value_ts:
                age_ms = round((now - entry.last_value_ts) * 1000)
                fresh  = age_ms < self._stale_ms
            else:
                age_ms = None
                fresh  = False

            keys[key] = {
                "observers":     entry.observer_count,
                "upstream_live": entry.upstream_live,
                "last_value":    entry.last_value,
                "age_ms":        age_ms,
                "fresh":         fresh,
                "gc_pending":    entry.gc_handle is not None,
            }
            total_observers += entry.observer_count

        # ops/sec = active upstream keys × reads per second
        ops_per_sec = round(self._active_upstream_subs * (1000.0 / self._poll_ms), 2) \
                      if self._poll_ms > 0 else 0.0

        return {
            "total_observers":      total_observers,
            "active_upstream_subs": self._active_upstream_subs,
            "ops_per_sec":          ops_per_sec,
            "poll_ms":              self._poll_ms,
            "stale_ms":             self._stale_ms,
            "gc_ms":                self._gc_ms,
            "keys":                 keys,
        }

    def close(self):
        """Dispose all upstream subscriptions and clear the cache."""
        for entry in list(self._entries.values()):
            if entry.gc_handle:
                entry.gc_handle.cancel()
                entry.gc_handle = None
            self._disconnect_upstream(entry)
        self._entries.clear()

    # ── internals ──────────────────────────────────────────────────────────────

    def _get_or_create(self, key: str) -> _KeyEntry:
        if key not in self._entries:
            self._entries[key] = _KeyEntry(
                key=key,
                subject=ReplaySubject(buffer_size=1),
            )
        return self._entries[key]

    def _connect_upstream(self, entry: _KeyEntry):
        """Subscribe *once* to the cold source; pipe values into the per-key Subject.

        This is called by ``observe()`` when the first observer subscribes.
        All subsequent observers tap into ``entry.subject`` directly — the upstream
        ``source.subscribe()`` is NOT called again.
        """
        if entry.upstream_live:
            return

        source = self._source_factory(entry.key)
        entry.upstream_sub_total += 1
        self._active_upstream_subs += 1
        entry.upstream_live = True

        log.debug(
            "QueryCache [%s] upstream CONNECTED (active upstream subs: %d)",
            entry.key, self._active_upstream_subs,
        )

        def on_next(value):
            entry.last_value    = value
            entry.last_value_ts = time.monotonic()
            entry.subject.on_next(value)

        def on_error(err):
            log.warning(
                "QueryCache [%s] upstream error: %s — retry in 2 s", entry.key, err
            )
            entry.upstream_live = False
            self._active_upstream_subs = max(0, self._active_upstream_subs - 1)
            entry.upstream_disp = None
            # auto-reconnect if observers are still waiting
            if entry.observer_count > 0:
                self._loop.call_later(2.0, lambda: self._connect_upstream(entry))

        def on_completed():
            # Polled sources (rx.interval) should never complete.
            log.warning("QueryCache [%s] upstream completed unexpectedly", entry.key)
            entry.upstream_live = False
            self._active_upstream_subs = max(0, self._active_upstream_subs - 1)
            entry.upstream_disp = None

        entry.upstream_disp = source.subscribe(
            on_next=on_next,
            on_error=on_error,
            on_completed=on_completed,
            scheduler=self._scheduler,
        )

    def _disconnect_upstream(self, entry: _KeyEntry):
        """Tear down the single upstream subscription for a key."""
        if not entry.upstream_live:
            return
        try:
            if entry.upstream_disp is not None:
                entry.upstream_disp.dispose()
        except Exception as exc:
            log.debug("QueryCache [%s] dispose error: %s", entry.key, exc)
        entry.upstream_disp = None
        entry.upstream_live = False
        self._active_upstream_subs = max(0, self._active_upstream_subs - 1)
        log.debug(
            "QueryCache [%s] upstream DISCONNECTED (active upstream subs: %d)",
            entry.key, self._active_upstream_subs,
        )

    def _gc_teardown(self, entry: _KeyEntry):
        """Called by the gc timer — disconnect upstream if still no observers."""
        entry.gc_handle = None
        if entry.observer_count == 0:
            log.debug("QueryCache [%s] gc teardown (no observers after gc_ms)", entry.key)
            self._disconnect_upstream(entry)
