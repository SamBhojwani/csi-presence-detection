"""
Recalibrate the movement threshold for the current setup.

The threshold is tied to GEOMETRY. Move the boards, change rooms, or
put the sender at a different height and the old number is wrong. This
walks through both measurements and works out a new one.

Requires capture_csi.py to be running in another terminal.

    .venv-mac/bin/python calibrate.py
"""

import importlib.util
import os
import re
import sys
import time

import numpy as np


CSV_FILE = "csi_capture.csv"

# Seconds recorded per phase
PHASE_SECONDS = 45

# Seconds you get to walk into position after pressing ENTER, before
# recording begins. You have to be at the keyboard to start the script
# but your demo position is usually somewhere else entirely - with a
# short buffer the "still" phase records you walking into place and
# calibrates against that, which produces a uselessly high threshold.
GET_READY_SECONDS = 15

# Seconds discarded at the start of each recording, for good measure
SETTLE_SECONDS = 3

# How far above the still baseline to place the threshold.
#
# Measured against the 99th percentile, NOT the maximum. A single
# stray spike - a twitch too short for drop_twitches to catch - would
# otherwise set the threshold on its own and wreck the sensitivity.
HEADROOM = 1.28
BASELINE_PERCENTILE = 99


# --------------------------------------------------
# Use the SAME scoring code the server uses, so the
# calibration cannot drift away from what runs live
# --------------------------------------------------

spec = importlib.util.spec_from_file_location("srv", "server.py")
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)


def capture_is_running():
    """The CSV must be growing, or there is nothing to measure."""

    if not os.path.exists(CSV_FILE):
        return False

    before = os.path.getsize(CSV_FILE)
    time.sleep(2.0)

    return os.path.getsize(CSV_FILE) > before


def get_ready():
    """Give the user time to walk to where they need to be."""

    for left in range(GET_READY_SECONDS, 0, -1):
        print(f"\r  get into position... {left:3d}s ", end="", flush=True)
        time.sleep(1)

    print("\r  RECORDING NOW - hold it              ")


def collect(seconds):
    """Record for `seconds`, then return the frames captured."""

    start = time.time()

    for left in range(seconds, 0, -1):
        print(f"\r  recording... {left:3d}s ", end="", flush=True)
        time.sleep(1)

    print("\r  recording... done   ")

    frames = []
    stamps = []

    with open(CSV_FILE, newline="") as f:

        f.readline()

        for line in f:

            try:
                t = float(line.split(",", 1)[0])
            except ValueError:
                continue

            if start + SETTLE_SECONDS <= t <= start + seconds:

                row = srv.parse_row(line)

                if row:
                    frames.append(row[2])
                    stamps.append(t - start)

    return frames, np.array(stamps)


def score_series(frames, step=10):
    """Run the live movement_score over a sliding window."""

    out = []
    index = []

    for end in range(srv.WINDOW, len(frames), step):

        window = frames[end - srv.WINDOW:end]

        width = len(window[-1])
        window = [f for f in window if len(f) == width]

        if len(window) < 2:
            continue

        out.append(srv.movement_score(srv.amplitudes(window)))
        index.append(end)

    return np.array(out), np.array(index)


def drop_twitches(scores):
    """
    Remove stretches where the subject actually moved during the
    'still' phase. Standing perfectly still for 45 seconds is hard,
    and one twitch left in the data inflates the threshold enough
    to destroy sensitivity - this happened twice by hand.

    Returns (mask_of_frames_to_keep, list_of_removed_runs).
    """

    median = np.median(scores)
    mad = np.median(np.abs(scores - median))

    cutoff = median + 6.0 * max(mad, 1e-9)

    hot = scores > cutoff

    runs = []
    start = None

    for i, h in enumerate(hot):

        if h and start is None:
            start = i

        if not h and start is not None:
            runs.append((start, i))
            start = None

    if start is not None:
        runs.append((start, len(hot)))

    runs = [r for r in runs if r[1] - r[0] >= 3]

    keep = np.ones(len(scores), bool)

    for a, b in runs:
        keep[max(0, a - 2):min(len(scores), b + 2)] = False

    return keep, runs


def looks_contaminated(scores):
    """
    A genuinely still phase is flat. If the readings are all over the
    place, the subject was moving and the whole phase is worthless -
    the twitch remover cannot save it, because it needs most of the
    data to be quiet in order to know what quiet looks like.
    """

    median = np.median(scores)

    if median <= 0:
        return False

    return float(scores.std() / median) > 0.6


def timeline(scores, cutoff):

    return "".join("^" if x > cutoff else "." for x in scores)


def write_threshold(value):

    with open("server.py", "rb") as f:
        data = f.read()

    pattern = re.compile(rb"THRESHOLD = [0-9.]+")

    if not pattern.search(data):
        print("Could not find THRESHOLD in server.py - edit it by hand.")
        return False

    data = pattern.sub(
        f"THRESHOLD = {value:.1f}".encode(),
        data,
        count=1
    )

    with open("server.py", "wb") as f:
        f.write(data)

    return True


# --------------------------------------------------

print()
print("==========================================")
print("        CSI THRESHOLD CALIBRATION")
print("==========================================")
print()
print(f"Window : {srv.WINDOW} frames")
print(f"Current threshold: {srv.THRESHOLD}")
print()

print("Checking the capture is running...")

if not capture_is_running():
    print()
    print("ERROR: csi_capture.csv is not growing.")
    print("Start the capture in another terminal first:")
    print("    .venv-mac/bin/python capture_csi.py")
    print()
    sys.exit(1)

print("  capture is live.")
print()

print("------------------------------------------")
print("PHASE 1 of 2 - STILL")
print("------------------------------------------")
print()
print("Stand (or sit) exactly where you will be during")
print("the demo, and keep as still as you can.")
print()
print("Do NOT measure this from another room. Calibrating")
print("against an empty path sets the bar far too low and")
print("it will false-fire the moment somebody stands there.")
print()
print(f"After you press ENTER you get {GET_READY_SECONDS} seconds to walk")
print("into position before recording starts.")
print()
input("Press ENTER...")
print()

get_ready()

still_frames, still_times = collect(PHASE_SECONDS)

if len(still_frames) < srv.WINDOW * 2:
    print("Not enough frames captured. Is the capture healthy?")
    sys.exit(1)

print(f"  {len(still_frames)} frames")
print()

print("------------------------------------------")
print("PHASE 2 of 2 - MOVING")
print("------------------------------------------")
print()
print("Move the way you will during the demo - walk between")
print("the boards, wave, lean in and out. Normal motion, not")
print("exaggerated: calibrate on violent movement and normal")
print("movement will not register.")
print()
print(f"Again, {GET_READY_SECONDS} seconds to get into position first.")
print()
input("Press ENTER...")
print()

get_ready()

move_frames, _ = collect(PHASE_SECONDS)

if len(move_frames) < srv.WINDOW * 2:
    print("Not enough frames captured.")
    sys.exit(1)

print(f"  {len(move_frames)} frames")
print()

print("Scoring...")

still_scores, still_index = score_series(still_frames)
move_scores, _ = score_series(move_frames)

keep, runs = drop_twitches(still_scores)
clean = still_scores[keep]

if looks_contaminated(still_scores):
    print()
    print("------------------------------------------")
    print("ABORTED - the still phase was not still")
    print("------------------------------------------")
    print()
    print(f"  spread {still_scores.std() / max(np.median(still_scores), 1e-9):.2f}"
          " (a still phase should be under 0.6)")
    print(f"  readings ranged {still_scores.min():.1f} to {still_scores.max():.1f}")
    print()
    print("  Something moved throughout. Usually this means you were")
    print("  still walking into position, or somebody else was in the")
    print("  room. Nothing has been changed.")
    print()
    print("  Run it again and stay put for the whole 45 seconds.")
    print()
    sys.exit(1)

print()
print("------------------------------------------")
print("RESULTS")
print("------------------------------------------")
print()

if runs:
    print(f"Discarded {len(runs)} stretch(es) where you moved during")
    print("the still phase:")

    for a, b in runs:
        ta = still_times[min(still_index[a], len(still_times) - 1)]
        tb = still_times[min(still_index[b - 1], len(still_times) - 1)]
        print(f"    t = {ta:5.1f}s to {tb:5.1f}s")

    print()

baseline = float(np.percentile(clean, BASELINE_PERCENTILE))

print(f"  STILL   n={len(clean):3d}  mean {clean.mean():6.2f}"
      f"  p{BASELINE_PERCENTILE} {baseline:6.2f}  max {clean.max():6.2f}")
print(f"  MOVING  n={len(move_scores):3d}  mean {move_scores.mean():6.2f}")
print(f"  separation {move_scores.mean() / max(clean.mean(), 1e-9):.2f}x")
print()

suggested = baseline * HEADROOM

false_alarms = 100.0 * (clean > suggested).mean()
detection = 100.0 * (move_scores > suggested).mean()

print(f"  still timeline : {timeline(still_scores, suggested)}")
print(f"  moving timeline: {timeline(move_scores, suggested)}")
print()
print(f"  SUGGESTED THRESHOLD: {suggested:.1f}")
print(f"    false alarms when still : {false_alarms:.1f}%")
print(f"    detection when moving   : {detection:.1f}%")
print()

if move_scores.mean() < clean.mean() * 1.8:
    print("  WARNING: separation is weak. The boards are probably")
    print("  too close together or the direct path is too strong.")
    print("  Move them further apart and run this again.")
    print()

if detection < 60:
    print("  WARNING: detection is low. Either the motion was too")
    print("  subtle, or the geometry needs improving.")
    print()

answer = input(f"Write THRESHOLD = {suggested:.1f} into server.py? [y/N] ")

if answer.strip().lower() == "y":

    if write_threshold(suggested):
        print()
        print("server.py updated. Restart the server to apply it:")
        print("    .venv-mac/bin/python server.py")
        print()

else:
    print()
    print("Left unchanged.")
    print()
