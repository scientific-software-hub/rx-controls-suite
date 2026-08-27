"""A conceptual D.LAB-shaped mock — Projects/Datasets/Jobs, not a reproduction
of the real DECTRIS D.LAB API (no public endpoint spec exists for it; see
demo/dectris-integration/dlab.py's module docstring).

Run:
    uv run --with fastapi --with "uvicorn[standard]" python app.py

Env: DLAB_HOST (default 0.0.0.0), DLAB_PORT (default 8090).
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

_RUNNING_DELAY_S = 0.15
_SETTLE_DELAY_S = 0.25


class DlabSim:
    """In-memory Projects/Datasets/Jobs state, plus deterministic fault injection.

    ``fault_mode``:

    - ``"nominal"``            — every job succeeds
    - ``"processing_failure"`` — every *new* job fails permanently
    - ``"flaky"``               — the next ``flaky_remaining`` job submissions
      fail, then it reverts to nominal — deterministic so a live demo can't
      land on a bad roll
    """

    def __init__(self) -> None:
        self.datasets: dict[str, dict] = {}
        self.jobs: dict[str, dict] = {}
        self._dataset_counter = 0
        self._job_counter = 0
        self.fault_mode = "nominal"
        self.flaky_remaining = 0

    def create_dataset(self, payload: dict) -> str:
        self._dataset_counter += 1
        dataset_id = f"ds-{self._dataset_counter}"
        self.datasets[dataset_id] = payload
        return dataset_id

    def create_job(self, dataset_id: str, template: str) -> str:
        if dataset_id not in self.datasets:
            raise KeyError(dataset_id)
        self._job_counter += 1
        job_id = f"job-{self._job_counter}"
        will_fail = False
        if self.fault_mode == "processing_failure":
            will_fail = True
        elif self.fault_mode == "flaky":
            if self.flaky_remaining > 0:
                will_fail = True
                self.flaky_remaining -= 1
                if self.flaky_remaining == 0:
                    self.fault_mode = "nominal"
        self.jobs[job_id] = {
            "job_id": job_id,
            "dataset_id": dataset_id,
            "template": template,
            "status": "queued",
            "result": None,
            "error": None,
            "_will_fail": will_fail,
        }
        asyncio.ensure_future(self._run_job(job_id))
        return job_id

    async def _run_job(self, job_id: str) -> None:
        job = self.jobs[job_id]
        await asyncio.sleep(_RUNNING_DELAY_S)
        job["status"] = "running"
        await asyncio.sleep(_SETTLE_DELAY_S)
        if job["_will_fail"]:
            job["status"] = "failed"
            job["error"] = "simulated processing failure"
        else:
            job["status"] = "succeeded"
            job["result"] = {"template": job["template"], "summary": "ok"}

    def set_fault(self, value: str) -> None:
        if value == "nominal":
            self.fault_mode, self.flaky_remaining = "nominal", 0
        elif value == "processing_failure":
            self.fault_mode, self.flaky_remaining = "processing_failure", 0
        elif value.startswith("flaky"):
            n = int(value.split(":", 1)[1]) if ":" in value else 2
            self.fault_mode, self.flaky_remaining = "flaky", n
        else:
            raise ValueError(f"unknown fault mode: {value}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.sim = DlabSim()
    yield


app = FastAPI(title="dlab_sim", lifespan=lifespan)


@app.post("/api/v1/projects/{project}/datasets")
async def create_dataset(project: str, request: Request):
    sim: DlabSim = request.app.state.sim
    body = await request.json()
    return {"dataset_id": sim.create_dataset(body)}


@app.post("/api/v1/jobs")
async def create_job(request: Request):
    sim: DlabSim = request.app.state.sim
    body = await request.json()
    try:
        job_id = sim.create_job(body["dataset_id"], body["template"])
    except KeyError:
        return JSONResponse(status_code=404, content={"error": "unknown dataset_id"})
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/v1/jobs/{job_id}")
async def get_job(job_id: str, request: Request):
    sim: DlabSim = request.app.state.sim
    job = sim.jobs.get(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"error": "unknown job_id"})
    return {k: v for k, v in job.items() if not k.startswith("_")}


@app.put("/_sim/fault")
async def put_fault(request: Request):
    sim: DlabSim = request.app.state.sim
    body = await request.json()
    try:
        sim.set_fault(body["value"])
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    return {"fault": body["value"]}


@app.get("/_sim/latest_job")
async def get_latest_job(request: Request):
    """Demo-dashboard convenience: the dashboard has no experiment-side
    handle to a specific job_id, so it polls "whatever the most recent job
    is" instead. Not part of any real D.LAB API."""
    sim: DlabSim = request.app.state.sim
    if sim._job_counter == 0:
        return {"job_id": None, "status": None}
    job_id = f"job-{sim._job_counter}"
    return {k: v for k, v in sim.jobs[job_id].items() if not k.startswith("_")}


if __name__ == "__main__":
    host = os.environ.get("DLAB_HOST", "0.0.0.0")
    port = int(os.environ.get("DLAB_PORT", "8090"))
    uvicorn.run(app, host=host, port=port, log_level="warning", loop="asyncio")
