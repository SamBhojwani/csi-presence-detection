# Demo Runbook

Device-free presence and motion detection from ESP32 Wi-Fi CSI.
Everything below assumes macOS and the `.venv-mac` virtualenv in this folder.

---

## Hardware

Two ESP32-S3 boards:

| Board | Firmware | Needs |
|---|---|---|
| **Sender** | `examples/get-started/csi_send` | 5 V only — a phone charger or power bank works. It broadcasts ESP-NOW at 100 packets/sec and is never read from. |
| **Receiver** | `examples/get-started/csi_recv` | USB to the laptop. This is the one the software talks to. |

The sender does **not** need the laptop. That is what lets you place it wherever the
signal is best rather than wherever a cable reaches.

---

## Start sequence

### 1. Position the boards

```bash
.venv-mac/bin/python capture_csi.py      # terminal 1, leave running
.venv-mac/bin/python signal_check.py     # terminal 2
```

Move the **sender** until the meter reads `GOOD`, then Ctrl+C.

**Position by the meter, not by distance.** There is no correct number of
centimetres — it depends on antenna orientation, what is between the boards, and the
room. Aim for a level of **30–70**:

- **Level too high** (say 120) — the direct path dominates. A person barely perturbs
  it. Measured separation in that state was 1.24x, which is unusable.
- **Level too low** (say 11) — CSI values become small integers and quantisation
  noise swamps the motion. The score cannot drop below ~9 no matter how still you are.

Stand still while reading the meter; your own movement moves the number.

### 2. Calibrate

```bash
.venv-mac/bin/python calibrate.py        # terminal 2
```

Two phases, 45 s each, with a 15 s countdown to walk into position first.

- **Phase 1 — STILL.** Stand where you will actually be during the demo. Do not
  measure this from another room: calibrating against an empty path sets the bar too
  low and it will false-fire the moment somebody stands there.
- **Phase 2 — MOVING.** Move the way you actually will. Not exaggerated — calibrate on
  violent movement and normal movement will not register. **Keep moving continuously**;
  pauses drag the reported detection rate down and make a working setup look broken.

Accept the suggested threshold if separation is above ~2.5x, detection above ~80 %,
and false alarms 0 %. Otherwise answer `n` and re-run.

### 3. Run it

```bash
.venv-mac/bin/python server.py           # terminal 2
```

Open **http://127.0.0.1:5001**

Port **5001**, not 5000. macOS AirPlay Receiver occupies 5000 and answers with
`403 Forbidden`.

---

## What good looks like

Current calibration (2026-08-30):

| | value |
|---|---|
| Threshold | 6.3 |
| Window | 90 frames (~1.2 s) |
| Standing still | score ≈ **4.7**, 🔵 NO MOVEMENT |
| Moving | score ≈ **17.6**, 🔴 MOVEMENT DETECTED |
| Separation | 3.76x |
| False alarms while still | 0 % across 278 readings |

Capture terminal should scroll `Frame ... | RSSI ... | CSI values 388` at roughly
60–80 rows/sec.

---

## If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `403 Forbidden` in the browser | You opened port 5000. That is macOS AirPlay. | Use **5001** |
| Dashboard shows ⚠️ CAPTURE STOPPED | The capture died or was never started | Restart terminal 1 |
| `ERROR: another capture_csi.py is already running` | A previous capture is still alive | `ps -eo pid,command \| grep capture_csi \| grep -v grep`, then stop it |
| `Resource busy` on the serial port | An ESP-IDF monitor has the port | Close the monitor in VS Code |
| Capture prints `no CSI_DATA on ...` forever | Sender unpowered, or receiver unplugged | Check both boards have power |
| Fires constantly while still | Boards moved since calibration | Re-run `signal_check.py` then `calibrate.py` |
| Never fires even when moving | Same — geometry changed | Same |

**The threshold is only valid for the geometry it was measured in.** If the boards
are bumped, moved, or set up in a different room, recalibrate. It takes about three
minutes.

---

## Notes for questions

**Why does a fan or another person set it off?**
The system has no model of *what* moved, only that the channel changed. Telling a
person from a fan is what the classifier stage is for — that is future work.

**Why does it not see me across the room?**
The sensitive region is a set of Fresnel ellipsoids around the two antennas, not a
tripwire between them. Motion near the boards registers; motion far outside that zone
does not.

**Would it detect a mosquito?**
No. At 2.4 GHz the wavelength is ~12.2 cm. A 3 mm insect is far smaller, putting it in
the Rayleigh scattering regime where scattered power falls as (size/λ)⁴ — about 10⁻⁷.

**Why not just difference consecutive frames?**
That was the first attempt and it failed. Raw CSI phase rotates ~π/2 between frames
from clock offset between the two chips, so the difference is mostly clock drift. Worse,
an un-normalised difference scales with signal strength, and a human body *attenuates*
the signal — so the score went down when a person was present. It detected absence.
The current metric uses per-subcarrier coefficient of variation over a window,
normalised by level: 3.76x separation against 1.24x for frame differencing.
