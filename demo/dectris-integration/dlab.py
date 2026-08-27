"""RxDlab — a conceptual client for a D.LAB-shaped processing service.

DECTRIS D.LAB has **no public endpoint specification** — its public docs
describe only concepts (Projects, Datasets, Jobs, Job Templates). This module
and ``dlab_sim/app.py`` model those concepts, not a reproduction of the real
API; say so out loud if it comes up in the meeting. See
``RxDectris/python/README.md``'s "what is simulated" table for the same
caveat applied to the detector side.

The point this makes: analysis becomes another composable, retryable stage
of the experiment — see ``recipes.py::process_with`` for how it plugs in.
"""

from __future__ import annotations

import asyncio

import httpx
import reactivex as rx


class DlabContext:
    """One HTTP client per D.LAB base URL — same shape as ``DetectorContext``."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = httpx.AsyncClient(base_url=self.base_url, timeout=10.0)

    async def aclose(self) -> None:
        await self.http.aclose()


class DlabError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RxDlab:
    """Upload a dataset, run a job template against it, await the result.

    Each method returns a single-shot ``rx.Observable`` — the same primitive
    shape as ``rxdectris``'s config/command calls — so it composes with
    ``ops.flat_map`` exactly like everything else in the suite.
    """

    def __init__(self, ctx: DlabContext, project: str = "rxdectris-demo") -> None:
        self._ctx = ctx
        self._project = project

    def upload(self, dataset: dict) -> rx.Observable:
        """POST a dataset summary (e.g. ``{"path": ..., "frames": ...}``);
        emits the new ``dataset_id``."""

        def subscribe(observer, scheduler=None):
            async def _run():
                try:
                    resp = await self._ctx.http.post(
                        f"/api/v1/projects/{self._project}/datasets", json=dataset
                    )
                    _raise_for_status(resp)
                    observer.on_next(resp.json()["dataset_id"])
                    observer.on_completed()
                except Exception as exc:
                    observer.on_error(exc)

            asyncio.ensure_future(_run())

        return rx.create(subscribe)

    def run_job(self, dataset_id: str, template: str) -> rx.Observable:
        """POST a job against *dataset_id*; emits the new ``job_id``."""

        def subscribe(observer, scheduler=None):
            async def _run():
                try:
                    resp = await self._ctx.http.post(
                        "/api/v1/jobs", json={"dataset_id": dataset_id, "template": template}
                    )
                    _raise_for_status(resp)
                    observer.on_next(resp.json()["job_id"])
                    observer.on_completed()
                except Exception as exc:
                    observer.on_error(exc)

            asyncio.ensure_future(_run())

        return rx.create(subscribe)

    def job_status(self, job_id: str) -> rx.Observable:
        """GET the current status of *job_id*; emits the full JSON body once."""

        def subscribe(observer, scheduler=None):
            async def _run():
                try:
                    resp = await self._ctx.http.get(f"/api/v1/jobs/{job_id}")
                    _raise_for_status(resp)
                    observer.on_next(resp.json())
                    observer.on_completed()
                except Exception as exc:
                    observer.on_error(exc)

            asyncio.ensure_future(_run())

        return rx.create(subscribe)

    def await_result(self, job_id: str, poll_ms: int = 200, timeout_s: float = 30.0) -> rx.Observable:
        """Poll ``job_status`` until it leaves ``queued``/``running``.

        Emits the final job body (``status`` is ``succeeded`` or ``failed``)
        and completes. Raises ``TimeoutError`` via ``on_error`` if the job
        never settles within *timeout_s* — a stuck job should not hang the
        demo forever.
        """

        def subscribe(observer, scheduler=None):
            async def _run():
                try:
                    elapsed = 0.0
                    while elapsed < timeout_s:
                        resp = await self._ctx.http.get(f"/api/v1/jobs/{job_id}")
                        _raise_for_status(resp)
                        body = resp.json()
                        if body["status"] in ("succeeded", "failed"):
                            observer.on_next(body)
                            observer.on_completed()
                            return
                        await asyncio.sleep(poll_ms / 1000)
                        elapsed += poll_ms / 1000
                    observer.on_error(TimeoutError(f"job {job_id} did not settle within {timeout_s}s"))
                except Exception as exc:
                    observer.on_error(exc)

            asyncio.ensure_future(_run())

        return rx.create(subscribe)


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code >= 400:
        raise DlabError(
            f"D.LAB {response.request.method} {response.request.url} -> {response.status_code}: {response.text}",
            status_code=response.status_code,
        )
