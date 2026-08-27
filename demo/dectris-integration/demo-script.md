# RxDECTRIS — meeting demo script (5–7 minutes)

Hero sentence, keep it visible: **DECTRIS already provides portable detector
and cloud APIs. RxDECTRIS demonstrates that the experiment orchestration
around those APIs can be portable too.**

Reveal, at the end: **The facility changed. The detector didn't. The
experiment recipe didn't either.**

## Before the meeting

```bash
cd demo/dectris-integration
docker compose up -d --build
docker compose ps                       # everything healthy
export EPICS_CA_AUTO_ADDR_LIST=NO EPICS_CA_ADDR_LIST=127.0.0.1
python facility_bridge.py &             # keep running for the whole meeting
uv run --with fastapi --with "uvicorn[standard]" python dashboard.py &
python inject_fault.py nominal          # baseline
```

Open the dashboard (`http://localhost:8020`) on screen next to a terminal.
Have `demo/dectris-integration/experiment.py` open in an editor, collapsed
to just the `experiment =` block — that's the whole pipeline on one screen.

## Step 1 — nominal run (∼1 min)

```bash
python experiment.py --facility tango --frames 100 --count-time 0.01
```

Let it run to completion without narrating operators yet — beam gate,
frames arriving, D.LAB upload, `processing: succeeded`. Let the behavior
speak first.

## Step 2 — beam loss (∼1 min)

```bash
python inject_fault.py beam_loss
python experiment.py --facility tango --frames 30 --count-time 0.02
```

Nothing happens — the gate holds, no `start` printed, dashboard shows Beam:
LOST in red. Then:

```bash
python inject_fault.py nominal
```

The run picks up and completes on its own — no restart needed.

## Step 3 — interlock (∼1 min)

Start a longer run, inject mid-flight from a second shell:

```bash
python experiment.py --facility tango --frames 200 --count-time 0.05
# in the other shell, ~2s in:
python inject_fault.py vacuum_burst
```

Dashboard's Interlock pill flips to TRIPPED; the terminal prints `ABORTED —
N/200 frames written`. Detector state on the dashboard returns to IDLE —
say out loud: *the detector always lands back in a safe state, whichever
fault fires.*

```bash
python inject_fault.py nominal
```

## Step 4 — D.LAB retry, detector untouched (∼1 min)

```bash
python inject_fault.py flaky_processing
python experiment.py --facility tango --frames 10 --count-time 0.02
```

One acquisition (`start`/`end` printed once), then `processing FAILED`,
then automatic retry, then `processing: succeeded`. This is the point to
land explicitly: *acquisition and processing are separate stages —
retrying one never re-triggers the other.*

## Step 5 — the reveal (∼1–2 min)

```bash
python experiment.py --facility epics --frames 100 --count-time 0.01
```

Same output shape as Step 1. Then show the two invocations side by side, or
scroll to `experiment.py`'s `--facility` argument and the two constructor
lines in `main()`:

```python
if args.facility == "tango":
    facility = TangoFacility(scheduler)
else:
    epics_ctx = EpicsContext()
    facility = EpicsFacility(epics_ctx, scheduler)
```

Say: **the facility changed, the detector didn't, and the experiment recipe
didn't either.**

## If asked, and only if time allows

- "Where else could this apply?" → the same adapter model (a small
  `Facility`/detector wrapper exposing Observables, composed with a handful
  of reusable recipes) could be built for DOOCS, Karabo, or BLISS — not
  that it exists today.
- The two prepared objection answers live in `README.md`'s closing section
  — read them there rather than improvising if either comes up.

## Fallback

If a container misbehaves live: `docker compose ps` to spot it,
`docker restart storage-ring-sim-server` fixes the one known flaky failure
mode (Tango `API_DeviceNotExported` after a DB-container restart). Keep a
terminal recording (`asciinema` or screen capture) of Steps 1–5 from a
rehearsal as a fallback if a live fix would eat the meeting's remaining
time.
