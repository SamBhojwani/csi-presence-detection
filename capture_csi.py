import serial
import csv
import re
import time
import os


PORT = "COM5"
BAUD = 921600
OUTPUT = "csi_capture.csv"


print()
print("======================================")
print("          ESP CSI CAPTURE")
print("======================================")
print()
print(f"Port : {PORT}")
print(f"Baud : {BAUD}")
print(f"CSV  : {OUTPUT}")
print()
print("Press CTRL+C to stop.")
print()


try:
    ser = serial.Serial(
        port=PORT,
        baudrate=BAUD,
        timeout=1
    )

except Exception as e:
    print("ERROR opening serial port:")
    print(e)
    raise SystemExit


print(f"Successfully opened {PORT}")
print("Waiting for CSI_DATA...")
print()


file_exists = os.path.exists(OUTPUT)

with open(
    OUTPUT,
    "a",
    newline="",
    encoding="utf-8"
) as f:

    writer = csv.writer(f)

    if not file_exists or os.path.getsize(OUTPUT) == 0:

        writer.writerow([
            "timestamp",
            "sequence",
            "rssi",
            "channel",
            "csi"
        ])

        f.flush()


    while True:

        try:

            line = ser.readline().decode(
                "utf-8",
                errors="ignore"
            ).strip()

            if not line:
                continue

            if not line.startswith("CSI_DATA,"):
                continue

            parts = line.split(",", 20)

            if len(parts) < 21:
                continue

            sequence = parts[1]
            rssi = parts[3]
            channel = parts[4]

            csi_text = parts[20].strip().strip('"')

            csi = re.findall(
                r"-?\d+",
                csi_text
            )

            if not csi:
                continue

            timestamp = time.time()

            writer.writerow([
                timestamp,
                sequence,
                rssi,
                channel,
                " ".join(csi)
            ])

            f.flush()

            print(
                f"Frame {sequence} | "
                f"RSSI {rssi} | "
                f"Channel {channel} | "
                f"CSI values {len(csi)}"
            )

        except KeyboardInterrupt:

            print()
            print("Stopping CSI capture...")
            break

        except Exception as e:

            print("Serial error:", e)
            break


ser.close()

print("Serial port closed.")