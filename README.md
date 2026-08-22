# Seismic-Sim Backend

This is a trimmed, deployment-only mirror of the live compute backend
from **[Seismic-Sim](https://github.com/nekrei/Seismic-Sim)** — an
earthquake-building-simulation project. It exists solely so the project's
GitHub Pages frontend (a static site, which can't run Python) has
somewhere to send its live "Building Parameters" recompute requests.

It exposes exactly one route, `POST /compute`, which reruns the same
modal/FFT building-response solver (`mdof_response.py`) as the main
project, against a cached earthquake record, for user-chosen building
parameters (stories, mass per floor, damping, target period).

**This repo has no frontend, no offline data pipeline, and nothing to run
locally beyond testing `/compute` directly.** For the full project — the
3D visualization, the physics writeup, the offline PEER-file-to-response
pipeline — see [nekrei/Seismic-Sim](https://github.com/nekrei/Seismic-Sim).

## Files

- `server.py` — the Flask app, trimmed to just `/compute` (no static-file
  serving — that's Pages' job).
- `mdof_response.py` — the physics engine (`MDOF_ShearBuilding`), an
  unmodified copy of the main project's file.
- `out/<record>/ground_accel.json` — cached ground-motion data per
  earthquake record, the only per-record input `/compute` needs.

## Running locally

```
pip install -r requirements.txt
python server.py
```

## Deployed via Render

Build command: `pip install -r requirements.txt`
Start command: `gunicorn server:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 60`

## Keeping this in sync

Whenever `server.py`'s `/compute` logic or `mdof_response.py` changes in
the main project, the same change needs to be mirrored here manually —
this repo is a plain duplicate, not a submodule or shared package.
