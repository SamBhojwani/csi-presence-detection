"""
Live signal meter for positioning the two boards.

There is a sweet spot. Too close and the direct path dominates, so a
person barely perturbs it. Too far and the CSI values get so small
that integer quantisation swamps the motion. This tells you which
side you are on, live, while you move the sender around.

Requires capture_csi.py to be running in another terminal.

    .venv-mac/bin/python signal_check.py
"""

import importlib.util
import time

import numpy as np


# Amplitude level we are aiming for. 48 is where the still/moving
# separation measured 3.74x; 124 (boards 40 cm apart) gave only 1.24x,
# and 11 put the noise floor above the motion.
TARGET_LOW = 30
TARGET_HIGH = 70


spec = importlib.util.spec_from_file_location("srv", "server.py")
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)


def reading():

    rows = srv.get_last_rows(srv.WINDOW)

    parsed = [
        p for p in (srv.parse_row(r) for r in rows)
        if p is not None
    ]

    if len(parsed) < 2:
        return None

    width = len(parsed[-1][2])
    parsed = [p for p in parsed if len(p[2]) == width]

    age = time.time() - parsed[-1][0]

    amplitude = srv.amplitudes([p[2] for p in parsed])
    active = amplitude[:, (amplitude > 0).mean(axis=0) > 0.9]

    return {
        "age": age,
        "rssi": float(np.mean([p[1] for p in parsed])),
        "level": float(active.mean()),
        "score": srv.movement_score(amplitude),
    }


print()
print("==========================================")
print("           SIGNAL POSITIONING")
print("==========================================")
print()
print("Move the SENDER around. Keep still yourself while")
print("reading the level - your own movement changes it.")
print()
print(f"Aim for a level between {TARGET_LOW} and {TARGET_HIGH}.")
print()
print("Press CTRL+C when you are happy, then run calibrate.py")
print()

try:

    while True:

        r = reading()

        if r is None:
            print("\r  waiting for data...            ", end="", flush=True)
            time.sleep(1)
            continue

        if r["age"] > 5:
            print(f"\r  STALE - capture stopped? ({r['age']:.0f}s old)      ",
                  end="", flush=True)
            time.sleep(1)
            continue

        level = r["level"]

        if level > TARGET_HIGH:
            verdict = "TOO CLOSE - direct path too strong"
        elif level < TARGET_LOW:
            verdict = "TOO FAR - quantisation noise will swamp motion"
        else:
            verdict = "GOOD"

        # quantisation step as a share of the signal
        step = 100.0 / max(level, 1e-9)

        print(
            f"\r  level {level:6.1f} | RSSI {r['rssi']:6.1f} dBm | "
            f"noise/step {step:4.1f}% | score {r['score']:6.1f} | "
            f"{verdict:<46}",
            end="",
            flush=True
        )

        time.sleep(1)

except KeyboardInterrupt:
    print()
    print()
    print("Done. Now recalibrate for this position:")
    print("    .venv-mac/bin/python calibrate.py")
    print()
