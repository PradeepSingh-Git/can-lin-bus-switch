"""
Bus Selector GUI (LIN + CAN) for Arduino Nano + CD74HC4067 board

Matches the unified Arduino firmware:
  - MODE LIN  -> LIN buses 1..32
  - MODE CAN  -> CAN buses 1..16
  - Selecting a bus sends either:
      LIN: "LIN <n>"  (or just <n> in LIN mode)
      CAN: "CAN <n>"  (or just <n> in CAN mode)

This GUI:
  - Lets you select COM port
  - Connect/Disconnect
  - Select Mode (LIN/CAN)
  - Select bus from dropdown
  - Activate / Default buttons
  - Console output (reads Arduino serial replies)

Requirements:
  pip install pyserial

Run:
  python3 bus_selector_gui.py
"""

import sys
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import serial
import serial.tools.list_ports


BAUDRATE = 9600

LIN_MAX = 32
CAN_MAX = 16

DEFAULT_LIN = 1
DEFAULT_CAN = 1


class BusSelectorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Bus Selector (LIN + CAN)")
        self.geometry("760x460")
        self.minsize(680, 420)

        self.ser = None
        self.reader_thread = None
        self.reader_stop = threading.Event()

        self.selected_port = tk.StringVar(value="")
        self.mode = tk.StringVar(value="LIN")  # "LIN" or "CAN"
        self.selected_bus = tk.StringVar(value=f"LIN_{DEFAULT_LIN}")

        self._build_ui()
        self._refresh_ports()
        self._rebuild_bus_list()  # ensure dropdown is correct

        # periodic port refresh (only when disconnected)
        self.after(1500, self._auto_refresh_ports)

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------- UI ----------------
    def _build_ui(self):
        main = ttk.Frame(self, padding=12)
        main.pack(fill="both", expand=True)

        # Row 1: COM + connect
        row1 = ttk.Frame(main)
        row1.pack(fill="x")

        ttk.Label(row1, text="COM Channel:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.port_combo = ttk.Combobox(row1, textvariable=self.selected_port, state="readonly", width=16)
        self.port_combo.grid(row=0, column=1, sticky="w")

        self.refresh_btn = ttk.Button(row1, text="Refresh", command=self._refresh_ports)
        self.refresh_btn.grid(row=0, column=2, sticky="w", padx=(8, 0))

        self.connect_btn = ttk.Button(row1, text="Connect", command=self.connect)
        self.connect_btn.grid(row=0, column=3, sticky="w", padx=(18, 0))

        self.disconnect_btn = ttk.Button(row1, text="Disconnect", command=self.disconnect, state="disabled")
        self.disconnect_btn.grid(row=0, column=4, sticky="w", padx=(8, 0))

        ttk.Separator(main).pack(fill="x", pady=10)

        # Row 2: Mode + Bus + buttons
        row2 = ttk.Frame(main)
        row2.pack(fill="x")

        ttk.Label(row2, text="Mode:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.mode_combo = ttk.Combobox(row2, textvariable=self.mode, values=["LIN", "CAN"], state="readonly", width=8)
        self.mode_combo.grid(row=0, column=1, sticky="w")
        self.mode_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_mode_change())

        ttk.Label(row2, text="Bus:").grid(row=0, column=2, sticky="w", padx=(18, 8))
        self.bus_combo = ttk.Combobox(row2, textvariable=self.selected_bus, state="readonly", width=20)
        self.bus_combo.grid(row=0, column=3, sticky="w")

        self.activate_btn = ttk.Button(row2, text="Activate", command=self.activate_selected, state="disabled")
        self.activate_btn.grid(row=0, column=4, sticky="w", padx=(12, 0))

        self.default_btn = ttk.Button(row2, text="Default", command=self.activate_default, state="disabled")
        self.default_btn.grid(row=0, column=5, sticky="w", padx=(8, 0))

        ttk.Separator(main).pack(fill="x", pady=10)

        # Console
        console_frame = ttk.Frame(main)
        console_frame.pack(fill="both", expand=True)

        ttk.Label(console_frame, text="Console:").pack(anchor="w")

        self.console = tk.Text(console_frame, height=16, wrap="word")
        self.console.pack(fill="both", expand=True, pady=(6, 0))

        scroll = ttk.Scrollbar(self.console, command=self.console.yview)
        self.console.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")

        self._log("Welcome to Bus Selector (LIN + CAN)")
        self._log(f"Baudrate: {BAUDRATE}")
        self._log("Select COM port and click Connect.")

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.console.insert("end", f"[{ts}] {msg}\n")
        self.console.see("end")

    # ---------------- Ports / Serial ----------------
    def _refresh_ports(self):
        ports = list(serial.tools.list_ports.comports())
        names = [p.device for p in ports]

        current = self.selected_port.get()
        self.port_combo["values"] = names

        if current in names:
            self.selected_port.set(current)
        elif names:
            self.selected_port.set(names[0])
        else:
            self.selected_port.set("")

    def _auto_refresh_ports(self):
        if self.ser is None:
            self._refresh_ports()
        self.after(1500, self._auto_refresh_ports)

    def connect(self):
        port = self.selected_port.get().strip()
        if not port:
            messagebox.showerror("No COM Port", "No COM port selected/found.")
            return

        try:
            self.ser = serial.Serial(port, BAUDRATE, timeout=0.1)
        except Exception as e:
            messagebox.showerror("Connection Error", f"Failed to open {port}:\n{e}")
            self.ser = None
            return

        self._log(f"Connected on {port}")

        self.connect_btn.configure(state="disabled")
        self.disconnect_btn.configure(state="normal")
        self.activate_btn.configure(state="normal")
        self.default_btn.configure(state="normal")
        self.port_combo.configure(state="disabled")
        self.refresh_btn.configure(state="disabled")

        # Start reader thread
        self.reader_stop.clear()
        self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader_thread.start()

        # Set mode + activate default to match current GUI state
        self.apply_mode_to_arduino()
        self.activate_default()

    def disconnect(self):
        self.reader_stop.set()
        try:
            if self.reader_thread and self.reader_thread.is_alive():
                self.reader_thread.join(timeout=0.5)
        except Exception:
            pass

        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass

        self.ser = None
        self._log("Disconnected.")

        self.connect_btn.configure(state="normal")
        self.disconnect_btn.configure(state="disabled")
        self.activate_btn.configure(state="disabled")
        self.default_btn.configure(state="disabled")
        self.port_combo.configure(state="readonly")
        self.refresh_btn.configure(state="normal")

    def _reader_loop(self):
        buf = bytearray()
        while not self.reader_stop.is_set():
            try:
                if not self.ser:
                    break
                data = self.ser.read(256)
                if data:
                    buf.extend(data)
                    while b"\n" in buf:
                        line, _, rest = buf.partition(b"\n")
                        buf = bytearray(rest)
                        text = line.decode(errors="replace").strip()
                        if text:
                            self.after(0, self._log, text)
                else:
                    time.sleep(0.05)
            except Exception:
                break

    def _send_line(self, s: str):
        if not self.ser:
            messagebox.showwarning("Not Connected", "Please connect to Arduino first.")
            return
        try:
            self.ser.write((s.strip() + "\n").encode("utf-8"))
        except Exception as e:
            messagebox.showerror("Send Error", f"Failed to send command:\n{e}")

    # ---------------- Mode / Bus logic ----------------
    def _rebuild_bus_list(self):
        m = self.mode.get().strip().upper()
        if m == "CAN":
            buses = [f"CAN_{i}" for i in range(1, CAN_MAX + 1)]
            # keep selection valid
            if not self.selected_bus.get().startswith("CAN_"):
                self.selected_bus.set(f"CAN_{DEFAULT_CAN}")
            self.bus_combo["values"] = buses
        else:
            buses = [f"LIN_{i}" for i in range(1, LIN_MAX + 1)]
            if not self.selected_bus.get().startswith("LIN_"):
                self.selected_bus.set(f"LIN_{DEFAULT_LIN}")
            self.bus_combo["values"] = buses

    def on_mode_change(self):
        self._rebuild_bus_list()
        # If connected, immediately tell Arduino to change mode
        if self.ser:
            self.apply_mode_to_arduino()

    def apply_mode_to_arduino(self):
        m = self.mode.get().strip().upper()
        if m not in ("LIN", "CAN"):
            return
        self._log(f"Setting mode -> {m}")
        self._send_line(f"MODE {m}")

    @staticmethod
    def _extract_number(s: str) -> int:
        digits = "".join(ch for ch in s if ch.isdigit())
        return int(digits) if digits else -1

    def activate_selected(self):
        m = self.mode.get().strip().upper()
        bus_str = self.selected_bus.get()

        n = self._extract_number(bus_str)
        if m == "CAN":
            if n < 1 or n > CAN_MAX:
                messagebox.showerror("Invalid CAN", f"Select CAN_1 .. CAN_{CAN_MAX}")
                return
            self._log(f"Activating CAN_{n} ...")
            self._send_line(f"CAN {n}")
        else:
            if n < 1 or n > LIN_MAX:
                messagebox.showerror("Invalid LIN", f"Select LIN_1 .. LIN_{LIN_MAX}")
                return
            self._log(f"Activating LIN_{n} ...")
            self._send_line(f"LIN {n}")

    def activate_default(self):
        m = self.mode.get().strip().upper()
        if m == "CAN":
            self.selected_bus.set(f"CAN_{DEFAULT_CAN}")
            self._log(f"Default → CAN_{DEFAULT_CAN}")
            self._send_line(f"CAN {DEFAULT_CAN}")
        else:
            self.selected_bus.set(f"LIN_{DEFAULT_LIN}")
            self._log(f"Default → LIN_{DEFAULT_LIN}")
            self._send_line(f"LIN {DEFAULT_LIN}")

    def on_close(self):
        try:
            self.disconnect()
        except Exception:
            pass
        self.destroy()


def main():
    app = BusSelectorApp()
    # Use a decent theme if available
    try:
        style = ttk.Style()
        if sys.platform.startswith("win"):
            style.theme_use("vista")
        else:
            # keep default; mac themes vary
            pass
    except Exception:
        pass
    app.mainloop()


if __name__ == "__main__":
    main()