from flask import Flask, jsonify, send_from_directory
import csv
import os
import numpy as np

app = Flask(__name__)

CSV_FILE = "csi_capture.csv"

# Higher = less sensitive
THRESHOLD = 12.0


# --------------------------------------------------
# Read only the last 2 rows of the CSV
# --------------------------------------------------

def get_last_rows():

    if not os.path.exists(CSV_FILE):
        return []

    try:
        with open(
            CSV_FILE,
            "r",
            encoding="utf-8",
            errors="ignore"
        ) as f:

            # Keep only the last 2 lines
            last_lines = []

            for line in f:
                if line.strip():
                    last_lines.append(line)

                    if len(last_lines) > 2:
                        last_lines.pop(0)

        if len(last_lines) < 2:
            return last_lines

        return last_lines

    except Exception as e:
        print("CSV ERROR:", e)
        return []


# --------------------------------------------------
# Parse CSV row
# --------------------------------------------------

def parse_row(line):

    try:
        parts = next(csv.reader([line]))

        if len(parts) < 5:
            return None

        return {
            "sequence": parts[1],
            "rssi": int(float(parts[2])),
            "channel": parts[3],
            "csi": np.array(
                [int(x) for x in parts[4].split()],
                dtype=float
            )
        }

    except Exception as e:
        print("PARSE ERROR:", e)
        return None


# --------------------------------------------------
# Get latest CSI data
# --------------------------------------------------

def get_latest_data():

    if not os.path.exists(CSV_FILE):
        return {
            "frames": 0,
            "rssi": 0,
            "movement": False,
            "score": 0.0
        }

    # Number of frames without loading the whole CSV
    try:
        with open(
            CSV_FILE,
            "rb"
        ) as f:

            frames = sum(1 for _ in f) - 1

    except Exception:
        frames = 0

    if frames <= 0:
        return {
            "frames": 0,
            "rssi": 0,
            "movement": False,
            "score": 0.0
        }

    lines = get_last_rows()

    if not lines:
        return {
            "frames": frames,
            "rssi": 0,
            "movement": False,
            "score": 0.0
        }

    latest = parse_row(lines[-1])

    if latest is None:
        return {
            "frames": frames,
            "rssi": 0,
            "movement": False,
            "score": 0.0
        }

    rssi = latest["rssi"]
    current = latest["csi"]

    score = 0.0

    # Compare latest frame with previous frame
    if len(lines) >= 2:

        previous = parse_row(lines[-2])

        if previous is not None:

            previous_csi = previous["csi"]

            n = min(
                len(current),
                len(previous_csi)
            )

            if n > 20:

                # Ignore unreliable edges
                start = 20
                end = min(360, n)

                difference = np.abs(
                    current[start:end]
                    -
                    previous_csi[start:end]
                )

                if len(difference) > 0:
                    score = float(
                        np.median(difference)
                    )

    movement = score > THRESHOLD

    return {
        "frames": frames,
        "rssi": rssi,
        "movement": movement,
        "score": round(score, 2)
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
        f"Score={result['score']} "
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
    print("Threshold:", THRESHOLD)
    print()
    print("Open:")
    print("http://127.0.0.1:5000")
    print()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False
    )