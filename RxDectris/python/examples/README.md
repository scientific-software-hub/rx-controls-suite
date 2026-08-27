# RxDectris examples — playbook

All scripts default to `--base-url http://localhost:8080`, the port
`simplon_sim` listens on (`demo/dectris-integration/simplon_sim`,
`docker compose up -d simplon-sim` from that directory, or run
`python app.py` directly for local testing).

| Script | What it shows |
|---|---|
| `read_state.py` | Single-shot status read — `read_status` |
| `acquire.py` | The `acquire_series` recipe end-to-end — the one to run first |
| `stream_frames.py` | Raw `stream2` usage; makes the subscribe-before-arm ordering explicit |
| `guarded_acquisition.py` | Gate acquisition on detector readiness — same idiom as the facility health gate in `demo/dectris-integration/recipes.py::wait_until_healthy` |
| `fluent_client.py` | `DectrisClient` fluent chain — read → arm → trigger → disarm |

```bash
uv pip install -e .
python examples/read_state.py
python examples/acquire.py --frames 20 --count-time 0.01
python examples/guarded_acquisition.py --frames 10
python examples/fluent_client.py
```
