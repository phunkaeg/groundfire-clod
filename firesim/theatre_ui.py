"""Channel-sized sparse-simulation viewer; synthetic fuel, no game connection."""
import math
import time
import tkinter as tk
from tkinter import ttk

from .adapters import EffectProjector
from .sparse import SparseFireSim


class TheatreLab:
    def __init__(self, root):
        self.root = root
        root.title("GroundFire — Channel scale laboratory")
        root.geometry("1190x745")
        self.paused = True
        self.count = tk.StringVar(value="64")
        self.speed = tk.StringVar(value="4")
        self.status = tk.StringVar()
        self.detail_title = tk.StringVar()
        toolbar = ttk.Frame(root, padding=8)
        toolbar.pack(fill="x")
        self.toggle_button = ttk.Button(toolbar, text="Run", command=self.toggle)
        self.toggle_button.pack(side="left")
        ttk.Button(toolbar, text="Step 1 second", command=self.step_once).pack(side="left", padx=6)
        ttk.Label(toolbar, text="Ignition locations").pack(side="left", padx=(12, 3))
        ttk.Combobox(toolbar, textvariable=self.count, values=("1", "4", "16", "64", "1000"), width=6,
                     state="readonly").pack(side="left")
        ttk.Button(toolbar, text="Reset", command=self.reset).pack(side="left", padx=6)
        ttk.Label(toolbar, text="Requested speed").pack(side="left", padx=(12, 3))
        ttk.Combobox(toolbar, textvariable=self.speed, values=("1", "2", "4", "8"), width=4,
                     state="readonly").pack(side="left")
        ttk.Label(toolbar, text="×").pack(side="left")
        ttk.Label(root, text="350 × 350 km coordinate envelope · synthetic grassland · no imported CloD map or game connection",
                  padding=(10, 2)).pack(anchor="w")
        content = ttk.Frame(root, padding=8)
        content.pack(fill="both", expand=True)
        left, right = ttk.Frame(content), ttk.Frame(content)
        left.pack(side="left", fill="both", expand=True)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        ttk.Label(left, text="Theatre — click an ignition marker to inspect it").pack(anchor="w")
        self.overview = tk.Canvas(left, width=560, height=560, bg="#10251b", highlightthickness=0)
        self.overview.pack(fill="both", expand=True)
        self.overview.bind("<Button-1>", self.select)
        ttk.Label(right, textvariable=self.detail_title).pack(anchor="w")
        self.detail = tk.Canvas(right, width=560, height=560, bg="#10251b", highlightthickness=0)
        self.detail.pack(fill="both", expand=True)
        ttk.Label(root, text="Markers show locations, not fire size. White rings: up to 24 selected visual sectors; all fires keep simulating.",
                  padding=(10, 2)).pack(anchor="w")
        ttk.Label(root, textvariable=self.status, padding=(10, 8), justify="left").pack(anchor="w")
        self.overview.bind("<Configure>", lambda event: self.draw())
        self.detail.bind("<Configure>", lambda event: self.draw())
        self.timer = None
        self.selected = 0
        self.reset()
        self.timer = root.after(100, self.tick)

    def reset(self):
        self.sim = SparseFireSim(35_000, 35_000)
        count = int(self.count.get())
        cols = math.ceil(math.sqrt(count))
        self.seeds = []
        for i in range(count):
            x, y = i % cols, i // cols
            east = round((5000 + x * 340000 / max(1, cols-1)) / 10) * 10 + 5
            north = round((5000 + y * 340000 / max(1, cols-1)) / 10) * 10 + 5
            self.seeds.append((east, north))
            self.sim.ignite(east, north, 4, 600, f"seed-{i}")
        self.selected = min(self.selected, len(self.seeds)-1)
        self.last_cost_ms = None
        self.draw()

    def toggle(self):
        self.paused = not self.paused
        self.toggle_button.configure(text="Run" if self.paused else "Pause")

    def step_once(self):
        started = time.perf_counter()
        self.sim.step(1)
        self.last_cost_ms = (time.perf_counter() - started) * 1000
        self.draw()

    def tick(self):
        started = time.perf_counter()
        if not self.paused:
            self.sim.step(0.5)
            self.last_cost_ms = (time.perf_counter() - started) * 1000
            self.draw()
        elapsed_ms = (time.perf_counter() - started) * 1000
        delay = max(20, round(500 / float(self.speed.get()) - elapsed_ms))
        self.timer = self.root.after(delay, self.tick)

    def geometry(self):
        width, height = self.overview.winfo_width(), self.overview.winfo_height()
        size = max(10, min(width, height) - 24)
        return (width-size)/2, (height-size)/2, size

    def select(self, event):
        ox, oy, size = self.geometry()
        east = (event.x-ox) / size * 350000
        north = (1-(event.y-oy)/size) * 350000
        self.selected = min(range(len(self.seeds)), key=lambda i:
                            (self.seeds[i][0]-east)**2 + (self.seeds[i][1]-north)**2)
        self.draw()

    def draw(self):
        if not hasattr(self, "sim"):
            return
        sim = self.sim
        effects = EffectProjector(budget=24).desired(sim)
        canvas = self.overview
        canvas.delete("all")
        ox, oy, size = self.geometry()
        canvas.create_rectangle(ox, oy, ox+size, oy+size, outline="#729d82")
        for km in (0, 100, 200, 300, 350):
            px, py = ox+km/350*size, oy+(1-km/350)*size
            canvas.create_line(px, oy, px, oy+size, fill="#254b36")
            canvas.create_line(ox, py, ox+size, py, fill="#254b36")
            canvas.create_text(px-4 if km == 350 else px+4, oy+size-9, text=f"{km}",
                               anchor="e" if km == 350 else "w", fill="#87a995")
        for effect in effects.values():
            x, y = ox+effect.east/350000*size, oy+(1-effect.north/350000)*size
            canvas.create_oval(x-6, y-6, x+6, y+6, outline="#e3eee6")
        for i, (east, north) in enumerate(self.seeds):
            x, y = ox+east/350000*size, oy+(1-north/350000)*size
            c = sim.cells.allocated.get(sim.index(int(east//10), int(north//10)))
            color = "#ff862d" if c and c.state == "flaming" else "#a8b4aa"
            canvas.create_oval(x-2, y-2, x+2, y+2, fill=color, outline="")
            if i == self.selected:
                canvas.create_rectangle(x-9, y-9, x+9, y+9, outline="#ffdc68", width=2)
        east, north = self.seeds[self.selected]
        cx, cy = int(east//10), int(north//10)
        self.detail_title.set(f"Ignition {self.selected+1} · 510 × 510 m detail · cells 10 m")
        canvas = self.detail
        canvas.delete("all")
        size = max(10, min(canvas.winfo_width(), canvas.winfo_height())-24)
        ox, oy = (canvas.winfo_width()-size)/2, (canvas.winfo_height()-size)/2
        palette = {"unburned":"#315d36", "heating":"#7c7040", "flaming":"#f68324",
                   "smoldering":"#73776e", "burned":"#272724"}
        for dy in range(-25,26):
            for dx in range(-25,26):
                x, y = cx+dx, cy+dy
                c = sim.cells.allocated.get(sim.index(x, y)) if 0 <= x < sim.width and 0 <= y < sim.height else None
                fill = palette[c.state] if c else palette["unburned"]
                x0, y0 = ox+(dx+25)*size/51, oy+(25-dy)*size/51
                canvas.create_rectangle(x0,y0,x0+size/51+0.5,y0+size/51+0.5,fill=fill,outline="")
        canvas.create_rectangle(ox,oy,ox+size,oy+size,outline="#729d82")
        s = sim.stats()
        cost = "—" if self.last_cost_ms is None else f"{self.last_cost_ms:.1f} ms"
        self.status.set(f"Time {sim.time:.1f} s    Allocated {s['allocated_cells']:,} / {s['potential_cells']:,} possible cells    "
                        f"Flaming {s['flaming']:,}    Smoldering {s['smoldering']:,}\n"
                        f"Active {len(sim.active):,}    Visual sectors {len(effects)} / 24    Last timed physics update {cost}    "
                        f"Wind 3 m/s east · uncalibrated model")

    def close(self):
        if self.timer:
            self.root.after_cancel(self.timer)
        self.root.destroy()


def main():
    root = tk.Tk()
    app = TheatreLab(root)
    root.protocol("WM_DELETE_WINDOW", app.close)
    root.mainloop()


if __name__ == "__main__":
    main()
