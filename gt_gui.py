"""Átirat-importer: egyszerű ablak a gt_pull motorhoz (Google Fordító átiratok mentése)."""

import logging
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import gt_pull as core

BASE_DIR = Path(__file__).resolve().parent
ICON = BASE_DIR / "atirat.ico"
OUT_DIR = core.OUT_DIR

logging.basicConfig(filename=BASE_DIR / "gt_gui.log", level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
log = logging.getLogger("gt_gui")

AUTO_STOP = 3  # ha a teteje már látszott, és az alja ennyi olvasáson át látszik: magától ment
GREEN, ORANGE, RED, BLUE, GREY = "#1a7f37", "#b35c00", "#b42318", "#0b57d0", "#5f6368"
FONT = "Segoe UI"


def fmt(n):
    return f"{n:,}".replace(",", " ")


class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.collector = self.stop = self.worker = None
        self.state = "idle"  # idle | collecting | finishing
        self.stable_reads = 0

        root.title("Átirat")
        root.geometry("560x330")
        root.minsize(480, 300)
        if ICON.is_file():
            try:
                root.iconbitmap(str(ICON))
            except tk.TclError:
                pass
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.report_callback_exception = self.on_tk_error

        top = tk.Frame(root)
        top.pack(fill="x", padx=20, pady=(16, 0))
        self.dot = tk.Label(top, text="●", font=(FONT, 14), fg=GREY)
        self.dot.pack(side="left")
        self.phone = tk.Label(top, text="Telefon keresése...", font=(FONT, 11), fg=GREY)
        self.phone.pack(side="left", padx=(6, 0))

        self.button = tk.Button(root, font=(FONT, 18, "bold"), fg="white", relief="flat",
                                activeforeground="white", pady=14, cursor="hand2", command=self.on_button)
        self.button.pack(fill="x", padx=20, pady=(16, 12))

        self.msg = tk.Label(root, font=(FONT, 13), justify="left", anchor="w", wraplength=510)
        self.msg.pack(fill="x", padx=20)

        tk.Button(root, text="Mappa megnyitása", font=(FONT, 10), relief="groove",
                  command=lambda: (OUT_DIR.mkdir(parents=True, exist_ok=True), os.startfile(OUT_DIR))
                  ).pack(side="bottom", anchor="w", padx=20, pady=16)

        self.set_idle("Nyisd meg az átiratot, nyomd meg a gombot,\n"
                      "tekerd FEL a tetejére, aztán LE az aljára.")
        threading.Thread(target=self.status_loop, daemon=True).start()
        root.after(150, self.pump)

    # ---------- megjelenés ----------

    def set_idle(self, text, color="black"):
        self.state = "idle"
        self.button.configure(text="▶  Import start", bg=GREEN, activebackground=GREEN, state="normal")
        self.msg.configure(text=text, fg=color)

    def show_progress(self):
        c = self.collector
        top = "✓" if c.top_seen else "–"
        bottom = "✓" if c.dumps and not c.bottom_clipped else "–"
        self.msg.configure(fg="black", text=(
            f"Olvasás...  {len(c.sections)} szekció · {fmt(len(c.text))} karakter\n"
            f"Teteje {top}     Alja {bottom}\n"
            "Tekerd FEL a tetejére és LE az aljára. Ha mindkettő ✓, magától ment."))

    # ---------- háttérszálak ----------

    def status_loop(self):
        while True:
            if self.state == "idle":
                try:
                    self.events.put(("status", core.device_status()))
                except Exception as e:  # noqa: BLE001 - az állapotjelzés ne álljon le
                    log.exception("Állapotlekérés hiba")
                    self.events.put(("status", {"state": "error", "error": str(e)}))
            threading.Event().wait(3)

    def run_poll(self):
        try:
            core.poll(self.collector, self.stop, emit=lambda k, d: self.events.put((k, d)))
        except Exception as e:  # noqa: BLE001
            log.exception("Gyűjtés hiba")
            self.events.put(("fatal", str(e)))

    def pump(self):
        try:
            while True:
                self.handle(*self.events.get_nowait())
        except queue.Empty:
            pass
        if self.state == "finishing" and not self.worker.is_alive():
            self.finish()
        self.root.after(150, self.pump)

    def handle(self, kind, data):
        if kind == "status":
            st = data.get("state")
            if st == "device" and data.get("translate"):
                self.dot.configure(fg=GREEN)
                self.phone.configure(text=f"{data.get('model') or 'Telefon'} · Fordító nyitva", fg="black")
            elif st == "device":
                self.dot.configure(fg=ORANGE)
                self.phone.configure(text="Nyisd meg a Fordítót a telefonon", fg="black")
            else:
                self.dot.configure(fg=RED)
                self.phone.configure(text="Nincs telefon (USB-kábel, USB-hibakeresés)", fg="black")
            return
        if kind == "fatal":
            self.state = "finishing"
            return
        if self.state != "collecting":
            return
        if kind == "section":
            self.stable_reads = 0
        elif kind == "dump":
            done = self.collector.top_seen and not self.collector.bottom_clipped
            self.stable_reads = self.stable_reads + 1 if done else 0
        self.show_progress()
        if self.stable_reads >= AUTO_STOP:
            self.stop_collecting()

    # ---------- műveletek ----------

    def on_button(self):
        if self.state == "idle":
            self.collector = core.Collector()
            self.stable_reads = 0
            self.stop = threading.Event()
            self.worker = threading.Thread(target=self.run_poll, daemon=True)
            self.state = "collecting"
            self.button.configure(text="■  Kész", bg=BLUE, activebackground=BLUE)
            self.show_progress()
            self.worker.start()
        elif self.state == "collecting":
            self.stop_collecting()

    def stop_collecting(self):
        self.stop.set()
        self.state = "finishing"
        self.button.configure(text="Mentés...", bg=GREY, activebackground=GREY, state="disabled")

    def finish(self):
        """Mindig ment, kérdés nélkül. Csak a pontosan azonos, már elmentett szöveget nem menti újra."""
        c = self.collector
        if not c.sections:
            self.set_idle("Nem sikerült szöveget olvasni.\nNyitva van a Fordítóban egy átirat?", RED)
            return
        stats = f"{len(c.sections)} szekció · {fmt(len(c.text))} karakter"
        content = core.render(c)
        dup = next((f for f in OUT_DIR.glob("*.md")
                    if f.read_text(encoding="utf-8", errors="replace") == content), None) \
            if OUT_DIR.is_dir() else None
        if dup:
            self.set_idle(f"Ez már megvolt ✓  {dup.name}\n{stats}", GREEN)
            return
        try:
            path = core.save(c, OUT_DIR)
        except OSError as e:
            log.exception("Mentés hiba")
            self.set_idle(f"Mentési hiba: {e}", RED)
            return
        log.info("Mentve: %s (%s, %d gap)", path, stats, c.gaps)
        if c.gaps:
            self.set_idle(f"Mentve ✓  {path.name}\n{stats}\nFigyelem: túl gyors görgetés, "
                          "kimaradhatott szekció.", ORANGE)
        else:
            self.set_idle(f"Mentve ✓  {path.name}\n{stats}", GREEN)

    def on_close(self):
        if self.stop:
            self.stop.set()
        self.root.destroy()

    def on_tk_error(self, exc, val, tb):
        log.error("Felületi hiba", exc_info=(exc, val, tb))
        messagebox.showerror("Hiba", f"{val}\n\nRészletek: {BASE_DIR / 'gt_gui.log'}")


def main():
    try:  # éles megjelenítés nagy DPI-n
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    if not Path(core.ADB).is_file():
        messagebox.showerror("Nincs adb", f"Nem található az adb:\n{core.ADB}")
        return
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
