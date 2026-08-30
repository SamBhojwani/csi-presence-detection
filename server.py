from flask import Flask, jsonify, send_from_directory
import csv
import os
import time
import numpy as np

app = Flask(__name__)

CSV_FILE = "csi_capture.csv"


# Subcarrier variability, in percent, above which we call it movement.
#
# Calibrated 2026-08-30 with the boards moved FAR APART (sender on a
# separate power supply, receiver at the laptop) and Sam STANDING in
# the path - that is the demo condition. Calibrate against an empty
# path and the bar ends up far too low.
#
#     still (n=301)  mean  7.38, max 10.93
#     moving (n=297) mean 27.61
#     separation     3.74x
#
# 14.0 gave 0 % false alarms and 98.7 % detection, with 28 % headroom
# above the worst still reading.
#
# Geometry is what made this work. At 40 cm apart the direct path was
# -33 dBm and separation was only 1.24x; far apart it is -37.8 dBm and
# separation is 3.74x. Recalibrate whenever the boards move.
THRESHOLD = 6.3

# Frames per reading. Capture runs at ~78 frames/sec in this setup,
# so 90 frames is roughly 1.2 seconds. Longer windows separate a
# little better but feel sluggish.
WINDOW = 90

# If the newest CSV row is older than this, the capture has stopped
# and the numbers on screen are stale. Without this the dashboard
# happily shows a frozen reading as if it were live.
STALE_AFTER = 3.0

# Each csi field is 4 header ints (sig_len, rx_format, len,
# first_word_invalid) followed by the CSI bytes themselves.
CSI_HEADER = 4


# --------------------------------------------------
# Count rows without re-reading the whole file
# --------------------------------------------------

_counter = {"size": 0, "count": 0}


def count_rows():

    if not os.path.exists(CSV_FILE):
        return 0

    size = os.path.getsize(CSV_FILE)

    # File was replaced or truncated - start over
    if size < _counter["size"]:
        _counter["size"] = 0
        _counter["count"] = 0

    if size > _counter["size"]:

        with open(CSV_FILE, "rb") as f:

            f.seek(_counter["size"])
            fresh = f.read(size - _counter["size"])

        _counter["count"] += fresh.count(b"\n")
        _counter["size"] = size

    # Minus the header line
    return max(_counter["count"] - 1, 0)


# --------------------------------------------------
# Read the last N rows by seeking from the end
# --------------------------------------------------

def get_last_rows(n):

    if not os.path.exists(CSV_FILE):
        return []

    size = os.path.getsize(CSV_FILE)

    # A CSI row is roughly 1.5 kB, so read generously
    want = min(size, (n + 2) * 4096)

    try:
        with open(CSV_FILE, "rb") as f:

            f.seek(size - want)
            chunk = f.read(want)

    except Exception as e:
        print("CSV ERROR:", e)
        return []

    lines = chunk.split(b"\n")

    # The first line is probably a partial row
    if want < size:
        lines = lines[1:]

    rows = [
        line.decode("utf-8", errors="ignore")
        for line in lines
        if line.strip()
    ]

    return rows[-n:]


# --------------------------------------------------
# Parse one CSV row into (timestamp, rssi, csi values)
# --------------------------------------------------

def parse_row(line):

    try:
        parts = next(csv.reader([line]))

        if len(parts) < 5:
            return None

        values = np.array(
            parts[4].split(),
            dtype=float
        )

        if len(values) <= CSI_HEADER:
            return None

        # values[2] is the CSI length the firmware reported.
        # Anything that disagrees is a truncated serial line.
        if len(values) != CSI_HEADER + int(values[2]):
            return None

        return (
            float(parts[0]),
            int(float(parts[2])),
            values[CSI_HEADER:]
        )

    except Exception:
        return None


# --------------------------------------------------
# CSI bytes are (imaginary, real) pairs per subcarrier
# --------------------------------------------------

def amplitudes(frames):

    matrix = np.array(frames)

    imaginary = matrix[:, 0::2]
    real = matrix[:, 1::2]

    return np.sqrt(imaginary ** 2 + real ** 2)


# --------------------------------------------------
# Movement score
#
# Three things matter here, and the old version got all
# three wrong:
#
#   1. Work on AMPLITUDE, not the raw interleaved values.
#      Raw phase spins ~pi/2 between frames from clock
#      offset between the two chips - that is not motion.
#
#   2. Divide by the signal level. An absolute difference
#      grows with signal strength, and a body ATTENUATES
#      the signal, so the old score read absence as motion.
#
#   3. Average over a window, not one frame pair.
# --------------------------------------------------

def movement_score(amplitude):

    if len(amplitude) < 2:
        return 0.0

    # Guard-band subcarriers are always zero - drop them
    active = (amplitude > 0).mean(axis=0) > 0.9

    if active.sum() < 8:
        return 0.0

    values = amplitude[:, active]

    # Drop dead frames rather than discarding the whole
    # window because of one of them
    values = values[values.mean(axis=1) > 0]

    if len(values) < 2:
        return 0.0

    mean = values.mean(axis=0)

    usable = mean > 0

    if usable.sum() < 8:
        return 0.0

    # Coefficient of variation: how much each subcarrier wobbles
    # across the window, relative to its own level. Frame-to-frame
    # differencing only saw 1.24x between still and moving here;
    # this sees 3.3x, because sustained motion decorrelates the
    # channel over the whole window rather than between two frames.
    spread = values[:, usable].std(axis=0) / mean[usable]

    return float(np.median(spread) * 100.0)


# --------------------------------------------------
# Get latest CSI data
# --------------------------------------------------

def get_latest_data():

    frames = count_rows()

    empty = {
        "frames": frames,
        "rssi": 0,
        "movement": False,
        "score": 0.0,
        "age": None,
        "live": False
    }

    if frames <= 0:
        return empty

    rows = get_last_rows(WINDOW)

    parsed = [
        p for p in (parse_row(r) for r in rows)
        if p is not None
    ]

    if not parsed:
        return empty

    # Mixed CSI lengths cannot go in one array - keep the
    # most recent run that agrees with the newest frame
    width = len(parsed[-1][2])

    parsed = [p for p in parsed if len(p[2]) == width]

    rssi = parsed[-1][1]

    # How long ago did the capture last write a row?
    age = max(time.time() - parsed[-1][0], 0.0)
    live = age <= STALE_AFTER

    if len(parsed) < 2:
        return {
            "frames": frames,
            "rssi": rssi,
            "movement": False,
            "score": 0.0,
            "age": round(age, 1),
            "live": live
        }

    score = movement_score(
        amplitudes([p[2] for p in parsed])
    )

    return {
        "frames": frames,
        "rssi": rssi,
        # A stale reading is not a detection
        "movement": bool(score > THRESHOLD and live),
        "score": round(score, 2),
        "age": round(age, 1),
        "live": live
    }


# --------------------------------------------------
# Frontend
# --------------------------------------------------

@app.route("/")
def index():

    return send_from_directory(
        ".",
        "index.html"
    )


# --------------------------------------------------
# API
# --------------------------------------------------

@app.route("/data")
def data():

    result = get_latest_data()

    print(
        f"Frames={result['frames']} "
        f"RSSI={result['rssi']} "
        f"Score={result['score']}% "
        f"Age={result['age']}s "
        f"Live={result['live']} "
        f"Movement={result['movement']}"
    )

    response = jsonify(result)

    # Prevent browser caching
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    return response


# --------------------------------------------------
# Start
# --------------------------------------------------

if __name__ == "__main__":

    print()
    print("================================")
    print("       ESP CSI MONITOR")
    print("================================")
    print()
    print("CSV:", CSV_FILE)
    print("Threshold:", THRESHOLD, "% subcarrier variability")
    print("Window:", WINDOW, "frames (~1.2 s)")
    print("Stale after:", STALE_AFTER, "s")
    print()
    print("Open:")
    print("http://127.0.0.1:5001")
    print()

    app.run(
        host="127.0.0.1",
        port=5001,
        debug=False
    )
