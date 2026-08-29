import csv
import numpy as np
import matplotlib.pyplot as plt

CSV_FILE = "csi_capture.csv"

frames = []
sequences = []

with open(CSV_FILE, newline="") as f:
    reader = csv.DictReader(f)

    for row in reader:
        values = [int(x) for x in row["csi"].split()]

        # Keep only proper 384-value CSI frames
        if len(values) == 384:
            frames.append(values)
            sequences.append(int(row["sequence"]))

print(f"Total CSV rows: {len(frames)}")
print(f"CSI frames used: {len(frames)}")

csi = np.array(frames)

print(f"CSI array shape: {csi.shape}")

# Plot magnitude of CSI
plt.figure(figsize=(12, 6))

# CSI is stored as I,Q pairs
i = csi[:, 12::2]
q = csi[:, 13::2]

magnitude = np.sqrt(i**2 + q**2)

plt.plot(magnitude[0])

plt.title("CSI Magnitude - First Frame")
plt.xlabel("Subcarrier")
plt.ylabel("Magnitude")
plt.grid(True)

plt.tight_layout()
plt.show()