"""Interactive desktop laboratory. Always offline; commands go to MemorySink."""
from pathlib import Path
import argparse
import json
import math
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .core import FireSim, FUELS
from .scenarios import village
from .adapters import EffectProjector, IL2Adapter, MemorySink, make_manifest
from .mission import export_group

COLORS = {"water": "#315c78", "road": "#666c70", "grass": "#839f4a", "woodland": "#31583d", "timber": "#b1946b", "masonry": "#a6a7a3"}


class Lab:
    def __init__(self, root):
        self.root = root
        root.title("GroundFire Lab — offline simulation")
        root.geometry("1180x820")
        root.minsize(950, 720)
        self.running = True
        self.last_wall = time.monotonic()
        self.speed = tk.DoubleVar(value=5)
        self.wind = tk.DoubleVar(value=3)
        self.angle = tk.DoubleVar(value=0)
        self.rain = tk.DoubleVar(value=0)
        self.embers = tk.BooleanVar(value=True)
        self.tool = tk.StringVar(value="ignite")
        self.status = tk.StringVar()
        self.hover = tk.StringVar(value="Click: ignition pulse · Right click: water drop · North is up")
        self.output = tk.StringVar()
        self.reset()
        controls = ttk.Frame(root, padding=8)
        controls.pack(fill="x")
        self.pause = ttk.Button(controls, text="Pause", command=self.toggle)
        self.pause.pack(side="left", padx=3)
        ttk.Button(controls, text="Reset scene", command=self.reset).pack(side="left", padx=3)
        ttk.Button(controls, text="Advance 10 s", command=self.advance).pack(side="left", padx=3)
        ttk.Button(controls, text="Save", command=self.save).pack(side="left", padx=3)
        ttk.Button(controls, text="Load", command=self.load).pack(side="left", padx=3)
        ttk.Button(controls, text="Export IL-2 group", command=self.export).pack(side="left", padx=3)
        ttk.Label(controls, text="Tool:").pack(side="left", padx=(15, 3))
        ttk.Combobox(controls, textvariable=self.tool, values=["ignite", "water drop", *FUELS], width=12, state="readonly").pack(side="left")
        settings = ttk.Frame(root, padding=(10, 0, 10, 4))
        settings.pack(fill="x")
        self.scale(settings, "Time ×", self.speed, 1, 20)
        self.scale(settings, "Wind m/s", self.wind, 0, 12)
        self.scale(settings, "Toward ° (0=E, 90=N)", self.angle, 0, 360)
        self.scale(settings, "Rain mm/h", self.rain, 0, 40)
        ttk.Checkbutton(settings, text="Ember spotting", variable=self.embers).pack(side="left", padx=10)
        ttk.Label(root, textvariable=self.status, padding=(10, 6), font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.canvas = tk.Canvas(root, background="#19242b", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=10)
        self.canvas.bind("<Button-1>", self.click)
        self.canvas.bind("<Button-3>", lambda event: self.click(event, True))
        self.canvas.bind("<Motion>", self.inspect)
        self.canvas.bind("<Configure>", lambda event: self.draw())
        ttk.Label(root, textvariable=self.hover, padding=(10, 6)).pack(anchor="w")
        ttk.Label(root, text="Green: fuel   Orange: flaming   Grey: smoldering   Dark: burned   Blue: water/wetting", padding=(10, 1)).pack(anchor="w")
        ttk.Label(root, textvariable=self.output, padding=(10, 4), foreground="#435165").pack(anchor="w")
        ttk.Label(root, text="Experimental spread model; coefficients are uncalibrated. No game is connected. Exported groups require placement and game validation.", padding=(10, 5)).pack(anchor="w")
        root.after(100, self.update)

    def scale(self, frame, title, variable, lo, hi):
        f = ttk.Frame(frame)
        f.pack(side="left", padx=5)
        label = ttk.Label(f)
        label.pack()
        def changed(*args):
            label.configure(text=f"{title}: {variable.get():.1f}")
        variable.trace_add("write", changed)
        changed()
        ttk.Scale(f, variable=variable, from_=lo, to=hi, length=170).pack()

    def reset(self):
        self.sim = village()
        self.sink = MemorySink()
        self.adapter = IL2Adapter(self.sink, make_manifest(self.sim), EffectProjector())
        self.last_wall = time.monotonic()
        if hasattr(self, "canvas"):
            self.draw()

    def toggle(self):
        self.running = not self.running
        self.pause.configure(text="Pause" if self.running else "Resume")
        self.last_wall = time.monotonic()

    def apply_weather(self):
        a = math.radians(self.angle.get())
        self.sim.wind_east, self.sim.wind_north = self.wind.get() * math.cos(a), self.wind.get() * math.sin(a)
        self.sim.rain_mm_h, self.sim.embers_enabled = self.rain.get(), self.embers.get()

    def advance(self):
        self.apply_weather()
        self.sim.step(10)
        self.adapter.synchronize(self.sim)
        self.draw()

    def update(self):
        now = time.monotonic()
        elapsed = min(0.3, now - self.last_wall)
        self.last_wall = now
        if self.running:
            self.apply_weather()
            self.sim.step(elapsed * self.speed.get())
        self.adapter.synchronize(self.sim)
        self.draw()
        self.root.after(100, self.update)

    def layout(self):
        return min(max(1, self.canvas.winfo_width() - 30) / self.sim.width,
                   max(1, self.canvas.winfo_height() - 20) / self.sim.height)

    def position(self, event):
        scale = self.layout()
        x = int((event.x - 10) / scale)
        y = self.sim.height - 1 - int((event.y - 10) / scale)
        if not 0 <= x < self.sim.width or not 0 <= y < self.sim.height:
            return None
        return x, y

    def click(self, event, water=False):
        pos = self.position(event)
        if pos is None:
            return
        x, y = pos
        e, n = self.sim.center(self.sim.index(x, y))
        tool = "water drop" if water else self.tool.get()
        if tool == "ignite":
            self.sim.ignite(e, n, 13, 900)
        elif tool == "water drop":
            self.sim.suppress(e, n, 22, 1600)
        else:
            self.sim.paint(x, y, tool)
        self.draw()

    def inspect(self, event):
        pos = self.position(event)
        if pos is not None:
            c = self.sim.cells[self.sim.index(*pos)]
            self.hover.set(f"Cell {pos[0]},{pos[1]} · {c.kind} / {c.state} · fuel {c.fuel:.1f} kg · moisture {c.moisture:.2f} kg/kg · heat {c.heat:.1f} kJ/m² · integrity {100*c.integrity:.0f}%")

    def draw(self):
        if not hasattr(self, "canvas"):
            return
        canvas = self.canvas
        canvas.delete("all")
        scale = self.layout()
        for i, c in enumerate(self.sim.cells):
            x = 10 + (i % self.sim.width) * scale
            y = 10 + (self.sim.height - 1 - i // self.sim.width) * scale
            color = COLORS[c.kind]
            if c.state == "flaming":
                color = "#f7a43e" if c.intensity < 0.6 else "#ed6029"
            elif c.state == "smoldering":
                color = "#72716b"
            elif c.state == "burned" or c.fuel < 0.8 * c.initial_fuel:
                color = "#33332e" if c.kind not in ("masonry", "timber") else "#6b6157"
            elif c.state == "heating":
                color = "#ad9d4a"
            if c.wetness > 0.35:
                color = "#468f9c"
            canvas.create_rectangle(x, y, x + scale, y + scale, fill=color, outline="")
            if c.kind in ("timber", "masonry"):
                canvas.create_rectangle(x + 1, y + 1, x + scale - 1, y + scale - 1, outline="#ddd0ad")
        # Bound visual plumes independently of cell count, like the game projection.
        for effect in self.adapter.projector.desired(self.sim).values():
            x = 10 + effect.east / self.sim.cell_size * scale
            y = 10 + (self.sim.height - effect.north / self.sim.cell_size) * scale
            r = 4 if effect.mode == "small" else 7
            dx = self.sim.wind_east * 2
            dy = -self.sim.wind_north * 2
            canvas.create_oval(x + dx - r, y + dy - r * 2, x + dx + r * 2, y + dy + r, fill="#b7bab6", outline="", stipple="gray50")
        x = max(70, canvas.winfo_width() - 100)
        canvas.create_line(x, 75, x + self.sim.wind_east * 4, 75 - self.sim.wind_north * 4, fill="#eeeeeb", width=3, arrow="last")
        canvas.create_text(x, 22, text="N ↑   Wind toward", fill="#eeeeeb")
        stats = self.sim.stats()
        self.status.set(f"{stats['time']:6.1f} s   |   Flaming {stats['flaming']}   Smoldering {stats['smoldering']}   Burned {stats['burned']}   |   Fuel consumed {stats['consumed_kg']:,.0f} kg")
        last = self.sink.commands[-1] if self.sink.commands else "waiting for fire-state changes"
        self.output.set(f"Offline IL-2 command preview · {len(self.sink.commands)} transitions · {len(self.adapter.current)}/24 effect sectors · {last}")

    def save(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("Fire snapshot", "*.json")])
        if path:
            Path(path).write_text(json.dumps(self.sim.snapshot()), encoding="utf-8")

    def load(self):
        path = filedialog.askopenfilename(filetypes=[("Fire snapshot", "*.json")])
        if path:
            try:
                self.sim = FireSim.restore(json.loads(Path(path).read_text(encoding="utf-8")))
                self.sink = MemorySink()
                self.adapter = IL2Adapter(self.sink, make_manifest(self.sim))
                self.wind.set(math.hypot(self.sim.wind_east, self.sim.wind_north))
                self.angle.set(math.degrees(math.atan2(self.sim.wind_north, self.sim.wind_east)) % 360)
                self.rain.set(self.sim.rain_mm_h)
                self.embers.set(self.sim.embers_enabled)
                self.draw()
            except (ValueError, KeyError, TypeError) as error:
                messagebox.showerror("Snapshot could not be loaded", str(error))

    def export(self):
        folder = filedialog.askdirectory(title="Export prepared IL-2 effect group")
        if folder:
            path, _ = export_group(self.sim, folder)
            messagebox.showinfo("Group exported", f"{path}\n\nPrepared effects only. Place at correct terrain elevation and validate in the Mission Editor before use.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--screenshot")
    args = parser.parse_args()
    # Establish DPI coordinates before Tk and ImageGrab use different Win32 APIs.
    import sys
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    root = tk.Tk()
    app = Lab(root)
    if args.smoke_test:
        app.running = False
        app.pause.configure(text="Resume")
        root.update()
        app.toggle()
        assert app.running
        app.toggle()
        assert not app.running
        app.angle.set(90)
        app.wind.set(4)
        app.apply_weather()
        assert abs(app.sim.wind_north - 4) < 1e-6 and abs(app.sim.wind_east) < 1e-6
        app.advance()
        assert app.sim.time == 10
        from types import SimpleNamespace
        scale = app.layout()
        event = SimpleNamespace(x=10 + 5.5 * scale, y=10 + (app.sim.height - 5.5) * scale)
        app.click(event)
        app.click(event, True)
        assert app.sim.cells[app.sim.index(5, 5)].wetness > 0
        app.reset()
        app.wind.set(3)
        app.angle.set(0)
        app.apply_weather()
        app.sim.step(150)
        app.adapter.synchronize(app.sim)
        app.draw()
        root.update()
        if args.screenshot:
            from PIL import ImageGrab
            # Capture only this application's window, independent of DPI/occlusion.
            import ctypes
            handle = ctypes.windll.user32.GetAncestor(root.winfo_id(), 2)
            ImageGrab.grab(window=handle).save(args.screenshot)
        assert app.sim.time == 150
        assert app.sink.commands
        print("Tk UI smoke test passed (pause/resume, weather, advance, ignition, water, reset and render):", app.sim.stats())
        root.destroy()
    else:
        root.mainloop()


if __name__ == "__main__":
    main()
