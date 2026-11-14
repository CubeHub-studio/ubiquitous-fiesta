"""Cubes Joy-Con Input Logger.

Reads controller state through pygame/SDL and writes input changes to a CSV file.
Joy-Cons paired over Windows Bluetooth may be exposed as separate devices.
"""
from __future__ import annotations

import csv
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import pygame
except ImportError:
    pygame = None


class JoyConLogger:
    POLL_HZ = 120
    DEVICE_REFRESH_SECONDS = 1.0

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Cubes Joy-Con Input Logger")
        self.root.geometry("760x520")
        self.root.minsize(620, 420)

        self.running = False
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.output_path: Path | None = None
        self.event_count = 0
        self.started_perf = 0.0
        self.csv_file = None
        self.csv_writer = None
        self.io_lock = threading.Lock()

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh_devices()

    def _build_ui(self):
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Joy-Con Input Logger",
                  font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text="Record button, stick, trigger, and D-pad changes from connected controllers."
        ).pack(anchor="w", pady=(3, 12))

        self.devices_var = tk.StringVar(value="Checking controllers…")
        ttk.Label(frame, textvariable=self.devices_var, wraplength=700).pack(
            anchor="w", pady=(0, 12)
        )

        controls = ttk.Frame(frame)
        controls.pack(fill="x")
        self.start_button = ttk.Button(
            controls, text="Start recording", command=self.start_recording
        )
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(
            controls, text="Stop recording", command=self.stop_recording,
            state="disabled"
        )
        self.stop_button.pack(side="left", padx=8)
        ttk.Button(
            controls, text="Refresh devices", command=self.refresh_devices
        ).pack(side="left")

        self.status_var = tk.StringVar(value="Ready. Pair the Joy-Cons in Windows Bluetooth settings.")
        ttk.Label(frame, textvariable=self.status_var, wraplength=700).pack(
            anchor="w", pady=(14, 4)
        )
        self.count_var = tk.StringVar(value="Input changes recorded: 0")
        ttk.Label(frame, textvariable=self.count_var).pack(anchor="w")

        ttk.Label(frame, text="Activity").pack(anchor="w", pady=(14, 4))
        self.activity = tk.Text(
            frame, height=12, state="disabled", wrap="word",
            font=("Consolas", 9)
        )
        self.activity.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="CSV contains UTC timestamp, elapsed time, device name, control type, "
                 "control index, and value. Control indexes are raw SDL indexes.",
            wraplength=700
        ).pack(anchor="w", pady=(10, 0))

    def _log(self, message: str):
        self.activity.configure(state="normal")
        self.activity.insert("end", f"[{datetime.now().strftime('%H:%M:%S')}] {message}\n")
        self.activity.see("end")
        self.activity.configure(state="disabled")

    def _require_pygame(self):
        if pygame is None:
            raise RuntimeError("pygame is missing. Install the EPA dependencies and try again.")
        pygame.init()
        pygame.joystick.init()

    def _get_device_summary(self) -> list[str]:
        self._require_pygame()
        result = []
        for device_index in range(pygame.joystick.get_count()):
            try:
                device = pygame.joystick.Joystick(device_index)
                device.init()
                result.append(
                    f"{device_index}: {device.get_name()} "
                    f"(axes: {device.get_numaxes()}, buttons: {device.get_numbuttons()}, "
                    f"hats: {device.get_numhats()})"
                )
            except pygame.error as exc:
                result.append(f"{device_index}: unavailable ({exc})")
        return result

    def refresh_devices(self):
        try:
            devices = self._get_device_summary()
            if devices:
                self.devices_var.set("Detected controllers:\n" + "\n".join(devices))
            else:
                self.devices_var.set(
                    "No controllers detected. Pair both Joy-Cons in Windows Settings > "
                    "Bluetooth & devices, then select Refresh devices."
                )
        except Exception as exc:
            self.devices_var.set(f"Controller detection unavailable: {exc}")

    def start_recording(self):
        if self.running:
            return
        try:
            self._require_pygame()
        except Exception as exc:
            messagebox.showerror("Controller support unavailable", str(exc))
            return

        if pygame.joystick.get_count() == 0:
            proceed = messagebox.askyesno(
                "No controllers detected",
                "Windows/SDL currently reports no controllers. Start anyway and wait "
                "for the Joy-Cons to appear?"
            )
            if not proceed:
                return

        filename = f"joycon-inputs-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
        selected = filedialog.asksaveasfilename(
            title="Save input recording",
            initialfile=filename,
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not selected:
            return

        try:
            self.csv_file = open(selected, "w", newline="", encoding="utf-8-sig")
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow([
                "timestamp_utc", "elapsed_seconds", "device",
                "control", "control_index", "value"
            ])
            self.csv_file.flush()
        except OSError as exc:
            self.csv_file = None
            self.csv_writer = None
            messagebox.showerror("Could not create CSV", str(exc))
            return

        self.output_path = Path(selected)
        self.event_count = 0
        self.started_perf = time.perf_counter()
        self.stop_event.clear()
        self.running = True
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_var.set(f"Recording to {self.output_path}")
        self._log(f"Recording started: {self.output_path}")
        self.worker = threading.Thread(target=self._record_loop, daemon=True)
        self.worker.start()

    def _record_loop(self):
        devices: dict[int, object] = {}
        previous: dict[int, dict[str, list]] = {}
        last_scan = 0.0
        last_flush = 0.0

        def write_event(name: str, control: str, index: int, value):
            elapsed = time.perf_counter() - self.started_perf
            timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            with self.io_lock:
                self.csv_writer.writerow([
                    timestamp, f"{elapsed:.6f}", name, control, index, repr(value)
                ])
                self.event_count += 1

        while not self.stop_event.is_set():
            try:
                pygame.event.pump()
                now = time.perf_counter()

                # Refresh the device list periodically, including devices connected mid-session.
                if now - last_scan >= self.DEVICE_REFRESH_SECONDS:
                    last_scan = now
                    count = pygame.joystick.get_count()
                    for device_index in range(count):
                        if device_index not in devices:
                            try:
                                dev = pygame.joystick.Joystick(device_index)
                                dev.init()
                                devices[device_index] = dev
                                previous.pop(device_index, None)
                                name = dev.get_name()
                                self.root.after(
                                    0, self._log, f"Controller connected: {name}"
                                )
                            except pygame.error:
                                pass

                    for device_index in list(devices):
                        if device_index >= count:
                            old = devices.pop(device_index, None)
                            previous.pop(device_index, None)
                            if old is not None:
                                self.root.after(
                                    0, self._log, f"Controller disconnected: {old.get_name()}"
                                )

                for device_index, dev in list(devices.items()):
                    try:
                        name = dev.get_name()
                        current = {
                            "axis": [round(dev.get_axis(i), 5)
                                     for i in range(dev.get_numaxes())],
                            "button": [int(dev.get_button(i))
                                       for i in range(dev.get_numbuttons())],
                            "hat": [tuple(dev.get_hat(i))
                                    for i in range(dev.get_numhats())],
                        }
                        old = previous.get(device_index, {})
                        for kind, values in current.items():
                            old_values = old.get(kind, [])
                            for control_index, value in enumerate(values):
                                if control_index >= len(old_values) or value != old_values[control_index]:
                                    write_event(name, kind, control_index, value)
                        previous[device_index] = current
                    except pygame.error:
                        devices.pop(device_index, None)
                        previous.pop(device_index, None)

                if now - last_flush >= 1.0:
                    with self.io_lock:
                        if self.csv_file:
                            self.csv_file.flush()
                    last_flush = now

                count = self.event_count
                self.root.after(0, self.count_var.set, f"Input changes recorded: {count}")
                time.sleep(1.0 / self.POLL_HZ)
            except Exception as exc:
                self.root.after(0, self._log, f"Logger error: {exc}")
                time.sleep(0.2)

        with self.io_lock:
            if self.csv_file:
                self.csv_file.flush()

    def stop_recording(self):
        if not self.running:
            return
        self.stop_event.set()
        if self.worker and self.worker.is_alive():
            self.worker.join(timeout=3)

        with self.io_lock:
            if self.csv_file:
                self.csv_file.close()
        self.csv_file = None
        self.csv_writer = None
        self.running = False

        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status_var.set(f"Recording saved: {self.output_path}")
        self._log(f"Recording stopped. {self.event_count} changes saved.")
        self.refresh_devices()

    def close(self):
        if self.running:
            self.stop_recording()
        try:
            if pygame is not None:
                pygame.joystick.quit()
                pygame.quit()
        except Exception:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    JoyConLogger(root)
    root.mainloop()


if __name__ == "__main__":
    main()
