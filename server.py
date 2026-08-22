"""
Live compute backend for Seismic-Sim's Building Parameters sliders.

This is a trimmed mirror of the main project's server.py, deployed
separately (Render) since GitHub Pages can only serve static files and
can't run this Flask app itself. It exposes only POST /compute -- the
frontend (served from GitHub Pages) fetches everything else (index.html,
out/*.json, out/*.csv, folders.json) directly from Pages, same-origin,
with no involvement from this backend at all.

See the main project (nekrei/Seismic-Sim) for the full app, including the
offline data pipeline and the local all-in-one dev server this was
trimmed from.

Run: gunicorn server:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 60
Local test: python server.py
"""
import json
import os
import struct

import numpy as np
from flask import Flask, Response, jsonify, request
from flask_cors import CORS

from mdof_response import MDOF_ShearBuilding

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(PROJECT_ROOT, "out")

app = Flask(__name__, static_folder=None)
CORS(app, resources={r"/compute": {"origins": "https://nekrei.github.io", "methods": ["POST", "OPTIONS"]}})

# Ground motion (acceleration + displacement) doesn't change with building
# parameters, so cache each record's parsed ground_accel.json in memory
# after the first request instead of re-reading it from disk every time.
_ground_cache = {}


def _load_ground(record):
    if record in _ground_cache:
        return _ground_cache[record]
    path = os.path.join(OUT_DIR, record, "ground_accel.json")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"No cached ground motion for record '{record}'")
    with open(path) as f:
        data = json.load(f)
    _ground_cache[record] = data
    return data


def _validate_params(body):
    """Clamp incoming slider values to sane bounds -- protects against
    pathological compute times or degenerate models, not against malice."""
    num_stories = max(1, min(30, int(body.get("num_stories", 7))))
    mass_per_floor = max(1e3, min(1e8, float(body.get("mass_per_floor", 1000e3))))
    zeta = max(0.005, min(0.5, float(body.get("zeta", 0.05))))
    t1_factor = max(0.01, min(2.0, float(body.get("T1_factor", 0.1))))
    return num_stories, mass_per_floor, zeta, t1_factor


@app.route("/compute", methods=["POST"])
def compute():
    body = request.get_json(force=True, silent=True) or {}
    record = body.get("record")
    if not record:
        return jsonify({"error": "record is required"}), 400

    try:
        ground = _load_ground(record)
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404

    num_stories, mass_per_floor, zeta, t1_factor = _validate_params(body)
    dt = ground["dt"]

    building = MDOF_ShearBuilding(
        num_stories, mass_per_floor=mass_per_floor, zeta=zeta, T1_factor=t1_factor
    )

    accel_x = np.array(ground["X"])
    disp_x = np.array(ground["X_disp"])
    time_arr, gdisp_x, _, abs_x = building.compute_response(accel_x, disp_x, dt)

    has_y = ground.get("Y") is not None
    if has_y:
        accel_y = np.array(ground["Y"])
        disp_y = np.array(ground["Y_disp"])
        # compute_response overwrites self.floor_disp_* per call, so this
        # second call for the Y component has to happen after X is read out.
        _, gdisp_y, _, abs_y = building.compute_response(accel_y, disp_y, dt)

    # The metadata (frequencies, mode shapes) is tiny -- JSON is fine for
    # it. The time-series arrays are not: at full resolution they're
    # hundreds of thousands of floats, and profiling showed JSON
    # encode+decode of that (not the actual physics, which takes ~20-50ms)
    # is what was blowing the live-recompute latency budget past 2 seconds
    # per request. Binary float32 transfer cuts both the payload size
    # (~5.5x, float32 vs ASCII decimal) and, more importantly, the
    # per-element text formatting/parsing cost that dominated the old
    # all-JSON response.
    header = {
        "num_stories": num_stories,
        "story_height": building.h,
        "natural_frequencies_Hz": (building.omega_n / (2 * np.pi)).tolist(),
        "mode_shapes": building.phi.tolist(),
        "npts": len(time_arr),
        "has_y": has_y,
    }
    header_bytes = json.dumps(header).encode("utf-8")
    # Float32Array requires its byte offset to be a multiple of 4, but the
    # JSON header's length isn't guaranteed to be -- pad with zero bytes so
    # the float data that follows always starts 4-byte aligned. The client
    # applies the same padding calculation when it reads header_len back out.
    pad = (-(4 + len(header_bytes))) % 4

    parts = [struct.pack("<I", len(header_bytes)), header_bytes, b"\x00" * pad]
    parts.append(time_arr.astype(np.float32).tobytes())
    parts.append(gdisp_x.astype(np.float32).tobytes())
    parts.append(abs_x.astype(np.float32).tobytes())  # (num_stories, npts), floor-major
    if has_y:
        parts.append(gdisp_y.astype(np.float32).tobytes())
        parts.append(abs_y.astype(np.float32).tobytes())

    return Response(b"".join(parts), mimetype="application/octet-stream")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"
    app.run(host=host, port=port, debug=False, threaded=True)
