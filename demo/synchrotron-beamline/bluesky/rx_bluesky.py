"""Rx ↔ Bluesky bridge — the entire integration in four small adapters.

The strategic claim of this module: rx-controls-suite does not compete with
Bluesky — it *feeds* it.  Bluesky's RunEngine owns orchestration (plans,
documents, suspend/resume, metadata); the rx wrappers own composition
(cross-control-system streams, polling pipelines, backpressure).  The two
meet at exactly four seams, each a few dozen lines:

    RxLoop     dedicated asyncio loop thread for all rx subscriptions
    RxStatus   Observable            →  Bluesky Status   (set / trigger)
    RxSignal   Observable            →  ophyd-Signal shim (suspenders)
    rx_wait    Observable            →  blocking first value (read)
    documents  RunEngine             →  Observable[(name, doc)]

Threading model
---------------
rxepics/rxtango observables schedule their work with ``asyncio.ensure_future``,
so every subscription must be made from a thread with a running event loop.
Bluesky's RunEngine runs its *own* loop on a background thread.  RxLoop
provides a second, rx-only loop; all bridges cross between the two with
``call_soon_threadsafe`` and never block one loop on the other:

    RE loop thread ──(call_soon_threadsafe)──▶ rx loop: subscribe pipelines
    rx loop thread ──(call_soon_threadsafe)──▶ RE loop: suspend / status done
"""

import asyncio
import threading
import time

import reactivex as rx
from reactivex.scheduler import ThreadPoolScheduler
from reactivex.scheduler.eventloop import AsyncIOThreadSafeScheduler
from reactivex.subject import Subject


# ── RxLoop ────────────────────────────────────────────────────────────────────

class RxLoop:
    """A dedicated asyncio event loop on a daemon thread for rx pipelines.

    ``scheduler`` is an AsyncIOThreadSafeScheduler bound to this loop — safe
    to hand to operators (``rx.interval``, ``sample``) from any thread.
    """

    def __init__(self):
        # The loop is created inside the thread that runs it: some loop
        # implementations (e.g. bliss's asyncio-gevent bridge, used by the
        # BLISS twin of this demo) bind to per-thread machinery at creation.
        ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run, args=(ready,), name="rx-loop", daemon=True,
        )
        self._thread.start()
        ready.wait()
        self.scheduler = AsyncIOThreadSafeScheduler(self.loop)

    def _run(self, ready: threading.Event) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.call_soon(ready.set)
        self.loop.run_forever()

    def run(self, coro):
        """Run *coro* on the rx loop and block the caller for its result.

        Used once at startup to create the caproto Context on the right loop.
        """
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result()

    def subscribe(self, observable: rx.Observable, **handlers):
        """Subscribe to *observable* on the rx loop thread (non-blocking).

        Returns a zero-arg dispose function, itself thread-safe.
        """
        cell = {}

        def _sub():
            cell["d"] = observable.subscribe(**handlers)

        self.loop.call_soon_threadsafe(_sub)

        def _dispose():
            self.loop.call_soon_threadsafe(
                lambda: cell["d"].dispose() if "d" in cell else None
            )

        return _dispose


# ── Observable → Status ───────────────────────────────────────────────────────

class RxStatus:
    """A Bluesky Status backed by an rx Observable.

    Completes when the observable completes; fails if it errors.  This one
    class is the whole bridge between the two worlds' notions of "done":

        motor.set(x)  →  RxStatus( write_pv(...) → poll MOVN until 0 )

    The RunEngine's own status callback is thread-safe (it re-dispatches via
    ``call_soon_threadsafe``), so firing callbacks from the rx loop is fine.
    """

    def __init__(self, observable: rx.Observable, rx_loop: RxLoop):
        self._event = threading.Event()
        self._exc = None
        self._callbacks = []
        self._lock = threading.Lock()
        rx_loop.subscribe(
            observable,
            on_error=self._finish,
            on_completed=lambda: self._finish(None),
        )

    def _finish(self, exc) -> None:
        with self._lock:
            self._exc = exc
            self._event.set()
            callbacks, self._callbacks = self._callbacks, []
        for cb in callbacks:
            cb(self)

    @property
    def done(self) -> bool:
        return self._event.is_set()

    @property
    def success(self) -> bool:
        return self._event.is_set() and self._exc is None

    def add_callback(self, cb) -> None:
        with self._lock:
            if not self._event.is_set():
                self._callbacks.append(cb)
                return
        cb(self)

    def exception(self, timeout=None):
        if not self._event.wait(timeout):
            raise TimeoutError("RxStatus: observable did not complete in time")
        return self._exc


# ── Observable → ophyd-Signal shim ────────────────────────────────────────────

class RxSignal:
    """Just enough of the ophyd.Signal API to drive Bluesky suspenders.

    Wraps any rx Observable as the "signal" a suspender watches:

        beam_ok = health.pipe(ops.map(lambda h: h.current >= 50))
        RE.install_suspender(SuspendBoolLow(RxSignal(beam_ok, rx_loop,
                                                     name="beam_ok")))

    Callbacks are fanned out on a private worker thread (not the rx loop):
    SuspenderBase briefly blocks its calling thread while creating an event
    on the RE loop, and the rx loop must stay free to serve device reads.
    """

    def __init__(self, observable: rx.Observable, rx_loop: RxLoop, *, name: str):
        self.name = name
        self.parent = None
        self._cbs = []
        self._value = None
        self._has_value = False
        self._pool = ThreadPoolScheduler(1)
        rx_loop.subscribe(
            observable.pipe(rx.operators.observe_on(self._pool)),
            on_next=self._emit,
        )

    def _emit(self, value) -> None:
        old, self._value = self._value, value
        self._has_value = True
        for cb in list(self._cbs):
            cb(value=value, old_value=old, timestamp=time.time(), obj=self)

    # — ophyd.Signal surface used by bluesky.suspenders —
    def subscribe(self, cb, event_type=None, run=True):
        self._cbs.append(cb)
        if run and self._has_value:
            cb(value=self._value, old_value=None, timestamp=time.time(), obj=self)

    def clear_sub(self, cb) -> None:
        if cb in self._cbs:
            self._cbs.remove(cb)

    def get(self):
        return self._value

    def __repr__(self) -> str:
        return f"RxSignal({self.name!r})"


# ── Observable → blocking value ───────────────────────────────────────────────

def rx_wait(observable: rx.Observable, rx_loop: RxLoop, timeout: float = 10.0):
    """Block until *observable* emits its first value, and return it.

    The synchronous half of the Readable protocol: Bluesky's ``read()`` is
    blocking, rx pipelines are not.  Safe to call from the RE loop thread —
    the pipeline runs on the rx loop, we only wait on an Event here.
    """
    event = threading.Event()
    cell = {}

    def on_next(v):
        if "v" not in cell:
            cell["v"] = v
            event.set()

    def on_error(e):
        cell["e"] = e
        event.set()

    dispose = rx_loop.subscribe(observable, on_next=on_next, on_error=on_error)
    try:
        if not event.wait(timeout):
            raise TimeoutError("rx_wait: no value within %.1fs" % timeout)
        if "e" in cell:
            raise cell["e"]
        return cell["v"]
    finally:
        dispose()


# ── RunEngine → Observable ────────────────────────────────────────────────────

def documents(RE) -> rx.Observable:
    """All RunEngine documents as an rx stream of ``(name, doc)`` tuples.

    The inverse bridge: once orchestration lives in Bluesky, the document
    stream comes *back* into rx, where share()/sample() give the same
    backpressure split as the pure-rx demo — HDF5 keeps every event, the
    display drops what it can't show.
    """
    subject = Subject()
    RE.subscribe(lambda name, doc: subject.on_next((name, doc)))
    return subject
