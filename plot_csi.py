import csv
import sys
from collections import deque

import numpy as np
import matplotlib.pyplot as plt

CSV_FILE = "csi_capture.csv"

# Only the most recent frames are kept. Loading the whole CSV would
# pull hundreds of MB of text into memory as Python ints.
MAX_FRAMES = 2000

# 4 header ints (sig_len, rx_format, len, first_word_invalid) sit in
# front of the CSI bytes themselves.
CSI_HEADER = 4

# Python's csv module refuses very long fields by default
csv.field_size_limit(10_000_000)


frames = deque(maxlen=MAX_FRAMES)
sequences = deque(maxlen=MAX_FRAMES)

total = 0
skipped = 0

with open(CSV_FILE, newline="") as f:

    reader = csv.DictReader(f)

    for row in reader:

        total += 1

        try:
            values = [int(x) for x in row["csi"].split()]
        except ValueError:
            skipped += 1
            continue

        # A row is well formed when its length matches the CSI length
        # the firmware reported in the header. That is 388 = 4 + 384
        # for this setup, NOT 384.
        if len(values) <= CSI_HEADER:
            skipped += 1
            continue

        if len(values) != CSI_HEADER + values[2]:
            skipped += 1
            continue

        frames.append(values[CSI_HEADER:])
        sequences.append(int(row["sequence"]))


print(f"Total CSV rows : {total}")
print(f"Malformed rows : {skipped}")
print(f"CSI frames used: {len(frames)}  (most recent {MAX_FRAMES} kept)")

if not frames:
    print("No usable CSI frames found.")
    sys.exit(1)

csi = np.array(frames)

print(f"CSI array shape: {csi.shape}")


# CSI is stored as (imaginary, real) pairs, one pair per subcarrier
imaginary = csi[:, 0::2]
real = csi[:, 1::2]

magnitude = np.sqrt(
    imaginary.astype(float) ** 2
    + real.astype(float) ** 2
)

print(f"Subcarriers    : {magnitude.shape[1]}")


fig, (top, bottom) = plt.subplots(
    2, 1,
    figsize=(12, 8)
)


# --- one frame, across the subcarriers
top.plot(
    magnitude[-1],
    label="most recent frame"
)

top.plot(
    magnitude.mean(axis=0),
    label=f"mean of {len(frames)} frames",
    linewidth=2
)

top.set_title("CSI Amplitude per Subcarrier")
top.set_xlabel("Subcarrier")
top.set_ylabel("Amplitude")
top.grid(True)
top.legend()


# --- all frames over time, as a heatmap
bottom.imshow(
    magnitude.T,
    aspect="auto",
    origin="lower",
    interpolation="nearest"
)

bottom.set_title("CSI Amplitude over Time")
bottom.set_xlabel("Frame")
bottom.set_ylabel("Subcarrier")


plt.tight_layout()
plt.show()
