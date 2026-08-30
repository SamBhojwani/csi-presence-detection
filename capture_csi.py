import serial
import serial.tools.list_ports as list_ports
import csv
import re
import sys
import time
import os

try:
    import fcntl
except ImportError:
    fcntl = None          # Windows - lock is skipped


# Leave as None to auto-detect the receiver: every candidate port is
# probed and the one actually emitting CSI_DATA wins. macOS renames
# these on replug and the two boards can swap, so hardcoding a path
# is how you lose a demo.
PORT = None
BAUD = 921600
OUTPUT = "csi_capture.csv"

# Seconds to wait before trying the serial port again after an error.
# Without this a single USB hiccup ended the capture for good, and the
# dashboard went on showing the last reading as if nothing happened.
RETRY_DELAY = 2.0

# Seconds to listen on a port before deciding it is not the receiver
PROBE_SECONDS = 2.0

# Field positions in the firmware's CSI_DATA line, for ESP32 / S3 / C3.
# Note field 4 is the RATE, not the channel - the old code read it as
# the channel and got 11 purely by coincidence.
FIELD_SEQUENCE = 1
FIELD_RSSI = 3
FIELD_CHANNEL = 16
FIELD_CSI = 20


print()
print("======================================")
print("          ESP CSI CAPTURE")
print("======================================")
print()
print(f"Port : {PORT or 'auto-detect'}")
print(f"Baud : {BAUD}")
print(f"CSV  : {OUTPUT}")
print()
print("Press CTRL+C to stop.")
print()


# --------------------------------------------------
# Only one capture may run at a time.
#
# Two instances do not fail loudly: the second cannot
# claim the port, sits in the retry loop, and its probe
# steals bytes from the one that IS working. The result
# is quietly corrupted data, which is far worse than an
# error message.
# --------------------------------------------------

LOCK_FILE = ".capture.lock"

_lock_handle = None

if fcntl is not None:

    _lock_handle = open(LOCK_FILE, "w")

    try:
        fcntl.flock(
            _lock_handle,
            fcntl.LOCK_EX | fcntl.LOCK_NB
        )

    except OSError:

        print("ERROR: another capture_csi.py is already running.")
        print()
        print("Find it with:")
        print("  ps -eo pid,command | grep capture_csi | grep -v grep")
        print()
        print("Stop that one first, or use it - two captures")
        print("fight over the serial port and corrupt the data.")
        print()

        sys.exit(1)


file_exists = os.path.exists(OUTPUT)


def candidate_ports():
    """USB serial devices, most likely first."""

    if PORT:
        return [PORT]

    found = [
        p.device
        for p in list_ports.comports()
        if "usbserial" in p.device or "usbmodem" in p.device
    ]

    return sorted(found)


def looks_like_receiver(port):
    """Open the port briefly and see if CSI_DATA comes out of it."""

    try:
        probe = serial.Serial(port, BAUD, timeout=0.5)

    except Exception:
        return None

    try:
        deadline = time.time() + PROBE_SECONDS

        while time.time() < deadline:

            line = probe.readline().decode(
                "utf-8",
                errors="ignore"
            )

            if line.startswith("CSI_DATA,"):
                return probe

    except Exception:
        pass

    probe.close()
    return None


def open_serial():
    """Keep trying until a receiver is found or the user gives up."""

    while True:

        ports = candidate_ports()

        if not ports:
            print("No USB serial devices found.")

        for port in ports:

            print(f"Probing {port} ...")

            found = looks_like_receiver(port)

            if found is not None:

                print(f"Receiver found on {port}")
                print()

                return found

            print(f"  no CSI_DATA on {port}")

        print(f"Retrying in {RETRY_DELAY:.0f}s... (CTRL+C to stop)")
        print()

        time.sleep(RETRY_DELAY)


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


    ser = None
    written = 0

    try:

        while True:

            if ser is None:
                ser = open_serial()

            try:

                line = ser.readline().decode(
                    "utf-8",
                    errors="ignore"
                ).strip()

            except Exception as e:

                # Unplugged, or the port glitched. Drop it and
                # reconnect instead of exiting.
                print()
                print("Serial error:", e)
                print("Reconnecting...")

                try:
                    ser.close()
                except Exception:
                    pass

                ser = None
                time.sleep(RETRY_DELAY)
                continue

            if not line:
                continue

            if not line.startswith("CSI_DATA,"):
                continue

            parts = line.split(",", FIELD_CSI)

            if len(parts) < FIELD_CSI + 1:
                continue

            sequence = parts[FIELD_SEQUENCE]
            rssi = parts[FIELD_RSSI]
            channel = parts[FIELD_CHANNEL]

            csi_text = parts[FIELD_CSI].strip().strip('"')

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

            written += 1

            print(
                f"Frame {sequence} | "
                f"RSSI {rssi} | "
                f"Channel {channel} | "
                f"CSI values {len(csi)}"
            )

            # The CSV grows about 320 MB per hour of capture
            if written % 20000 == 0:

                size_mb = os.path.getsize(OUTPUT) / (1024 * 1024)

                print()
                print(f"  [ {OUTPUT} is now {size_mb:.0f} MB ]")
                print()

    except KeyboardInterrupt:

        print()
        print("Stopping CSI capture...")


    finally:

        if ser is not None:

            try:
                ser.close()
                print("Serial port closed.")
            except Exception:
                pass
