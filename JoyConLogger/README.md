# Cubes Joy-Con Input Logger

A Windows desktop application that records raw controller input changes to CSV.

## Features

- Detects game controllers exposed to Windows through SDL/pygame.
- Records button states, analog axes, and hat/D-pad values.
- Records both Joy-Cons independently when Windows exposes them as separate devices.
- Includes UTC timestamps and elapsed time for every change.
- Checks periodically for controllers connected or disconnected during a recording.
- Writes CSV locally; no network connection or telemetry.

## Build with CubesEPA

From the repository root:

```powershell
cubes create .\JoyConLogger --publisher "Cubes, Studio." --app-version 1.0.0
cubes verify .\JoyConLogger.epa
```

## Run

Pair the Joy-Cons in Windows Settings > Bluetooth & devices. Run the generated EPA, accept the CubesEPA safety confirmation, click **Refresh devices**, then **Start recording** and choose a CSV destination. Click **Stop recording** to finish.

## CSV columns

- `timestamp_utc`: UTC ISO-8601 timestamp
- `elapsed_seconds`: time since recording began
- `device`: controller name reported by SDL
- `control`: `button`, `axis`, or `hat`
- `control_index`: raw zero-based SDL control index
- `value`: numeric state/value (hat values are pairs)

## Compatibility notes

Joy-Cons may appear as two independent devices. Windows and SDL determine which controls are exposed and their indexes; this app does not assume a universal Nintendo button mapping. This initial version records standard SDL joystick inputs only. It does not decode Joy-Con motion/gyro sensors or merge the pair into one virtual controller.

If no controller appears, verify that both Joy-Cons are paired in Windows Bluetooth settings and that Windows exposes them as game-controller devices. Some Bluetooth/driver combinations may require a controller mapping or a different input backend.

## Dependencies

CubesEPA installs the package listed in `requirements.txt` when the EPA is run:

```text
pygame-ce>=2.5.6,<3
```
