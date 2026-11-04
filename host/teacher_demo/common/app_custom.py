"""Local desktop UI for the physical Kria FPGA LDPC image demonstration."""
from pathlib import Path
from datetime import datetime
import csv
import json
import math
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np
from PIL import Image, ImageTk
from codec import Codec, prepare_image, evaluate
from fpga_bridge import probe, run_hardware, Cancelled, ROOT

BG, PANEL, CARD, TEXT, MUTED, INK = "#ffffff", "#f3f3f3", "#ffffff", "#111111", "#666666", "#111111"

DEMO_VERSION = "unspecified"
NOISE_DB_MIN, NOISE_DB_MAX = -10.0, 20.0

def parse_channel_settings(db_text, seed_text):
    try:
        db = float(db_text)
    except (ValueError, TypeError):
        raise ValueError("Enter a numeric Eb/N0 value in dB.") from None
    if not math.isfinite(db) or not NOISE_DB_MIN <= db <= NOISE_DB_MAX:
        raise ValueError("Eb/N0 must be between -10 and 20 dB. Lower values mean stronger noise.")
    try:
        seed = int(str(seed_text).strip())
    except (ValueError, TypeError):
        raise ValueError("The noise seed must be an integer.") from None
    if not 0 <= seed <= 2147483647:
        raise ValueError("The noise seed must be between 0 and 2147483647.")
    return db, seed

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LDPC FPGA Image Lab v2 - Noise and Iteration Comparison")
        self.geometry("1440x960")
        self.minsize(1080, 740)
        self.configure(bg=BG)
        self.option_add("*TCombobox*Listbox.background", "#ffffff")
        self.option_add("*TCombobox*Listbox.foreground", "#111111")
        self.option_add("*TCombobox*Listbox.selectBackground", "#111111")
        self.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        self.codec = Codec()
        self.events = queue.Queue()
        self.cancel_event = threading.Event()
        self.file = None
        self.busy = False
        self.cards = []
        self.input_controls = []
        self.last_folder = ROOT / "runs"
        self.result_count = 0
        self.build_ui()
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self.after(80, self.poll_events)
        self.select_file(ROOT / "assets" / "demo.png")

    def build_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), background=PANEL, foreground=TEXT)
        style.configure("TButton", padding=(12, 8), background="#ffffff", foreground=TEXT,
                        bordercolor="#cccccc", lightcolor="#ffffff", darkcolor="#cccccc", borderwidth=1)
        style.map("TButton", background=[("active", "#e5e5e5"), ("disabled", "#eeeeee")],
                  foreground=[("disabled", "#999999")])
        style.configure("Primary.TButton", background="#111111", foreground="#ffffff", font=("Segoe UI", 11, "bold"), padding=(16, 13))
        style.map("Primary.TButton", background=[("disabled", "#bbbbbb"), ("active", "#333333")],
                  foreground=[("disabled", "#ffffff"), ("active", "#ffffff")])
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT, padding=4)
        style.map("TCheckbutton", background=[("active", PANEL)])
        style.configure("TCombobox", fieldbackground="#ffffff", foreground=TEXT, padding=5)
        style.map("TCombobox", fieldbackground=[("readonly", "#ffffff")],
                  selectbackground=[("readonly", "#ffffff")], selectforeground=[("readonly", TEXT)])
        style.configure("TSpinbox", fieldbackground="#ffffff", foreground=TEXT, padding=5)
        style.configure("TProgressbar", background=INK, troughcolor="#e2e2e2", borderwidth=0)
        style.configure("Preset.TButton", padding=(4, 6))
        style.configure("Horizontal.TScale", background="#ffffff", troughcolor="#dddddd",
                        bordercolor="#999999", lightcolor="#ffffff", darkcolor="#999999")
        style.map("Horizontal.TScale", background=[("active", "#eeeeee")])
        style.configure("Vertical.TScrollbar", background="#e2e2e2", troughcolor="#f5f5f5",
                        bordercolor="#cccccc", arrowcolor="#333333",
                        lightcolor="#ffffff", darkcolor="#bbbbbb")
        style.map("Vertical.TScrollbar", background=[("active", "#cccccc")])
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=26, pady=(20, 14))
        tk.Label(header, text="LDPC FPGA Image Lab v2", bg=BG, fg=TEXT,
                 font=("Segoe UI", 23, "bold")).pack(side="left")
        tk.Label(header, text="  BPSK / AWGN → NMS → AXI DMA", bg=BG, fg=MUTED,
                 font=("Segoe UI", 11)).pack(side="left", padx=12)
        tk.Label(header, text="HARDWARE MODE", bg="#111111", fg="#ffffff",
                 font=("Segoe UI", 10, "bold"), padx=12, pady=7).pack(side="right")
        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True, padx=24, pady=(0, 18))
        sidebar = tk.Frame(main, bg=PANEL, width=300)
        sidebar.pack(side="left", fill="y", padx=(0, 18))
        sidebar.pack_propagate(False)
        self.side_canvas = tk.Canvas(sidebar, bg=PANEL, highlightthickness=0)
        side_scroll = ttk.Scrollbar(sidebar, orient="vertical", command=self.side_canvas.yview)
        side_scroll.pack(side="right", fill="y")
        self.side_canvas.configure(yscrollcommand=side_scroll.set)
        self.side_canvas.pack(side="left", fill="both", expand=True)
        controls = tk.Frame(self.side_canvas, bg=PANEL)
        side_window = self.side_canvas.create_window((16, 12), window=controls, anchor="nw")
        controls.bind("<Configure>", lambda _: self.side_canvas.configure(scrollregion=self.side_canvas.bbox("all")))
        self.side_canvas.bind("<Configure>", lambda e: self.side_canvas.itemconfigure(side_window, width=e.width-28))

        def heading(text):
            tk.Label(controls, text=text, bg=PANEL, fg=INK,
                     font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x", pady=(10, 8))
        def button(text, command, **options):
            b = ttk.Button(controls, text=text, command=command, **options)
            b.pack(fill="x", pady=3)
            self.input_controls.append((b, "normal"))
            return b

        heading("01  IMAGE")
        button("Choose image...", self.browse)
        self.file_label = tk.Label(controls, text="No image selected", bg=PANEL, fg=MUTED,
                                   wraplength=260, anchor="w", justify="left")
        self.file_label.pack(fill="x", pady=(4, 5))
        button("Load sample image", lambda: self.select_file(ROOT / "assets" / "demo.png"))
        heading("02  CHANNEL AND SIZE")
        tk.Label(controls, text="Image bounds (aspect ratio preserved)", bg=PANEL, fg=MUTED, anchor="w").pack(fill="x")
        self.size = tk.StringVar(value="128 × 96  /  Presentation")
        combo = ttk.Combobox(controls, textvariable=self.size, state="readonly",
                             values=["64 × 48  /  Quick", "128 × 96  /  Presentation", "256 × 192  /  Full image"])
        combo.pack(fill="x", pady=(4, 8))
        self.input_controls.append((combo, "readonly"))
        row = tk.Frame(controls, bg=PANEL)
        row.pack(fill="x")
        tk.Label(row, text="Eb/N0 (dB)", bg=PANEL, fg=TEXT).pack(side="left")
        self.db = tk.StringVar(value="3.0")
        self.db_slider_value = tk.DoubleVar(value=3.0)
        db = ttk.Spinbox(row, from_=NOISE_DB_MIN, to=NOISE_DB_MAX, increment=.5,
                         textvariable=self.db, width=8)
        db.pack(side="right")
        db.bind("<FocusOut>", self.sync_noise_slider)
        db.bind("<Return>", self.sync_noise_slider)
        self.input_controls.append((db, "normal"))
        noise_slider = ttk.Scale(controls, from_=NOISE_DB_MIN, to=NOISE_DB_MAX,
                                 variable=self.db_slider_value, command=self.on_noise_slide)
        noise_slider.pack(fill="x", pady=(7, 0))
        self.input_controls.append((noise_slider, "normal"))
        presets = tk.Frame(controls, bg=PANEL)
        presets.pack(fill="x", pady=(5, 0))
        for preset in (0, 3, 6):
            preset_button = ttk.Button(presets, text=f"{preset} dB", width=6,
                                       style="Preset.TButton", command=lambda value=preset: self.set_noise_db(value))
            preset_button.pack(side="left", fill="x", expand=True, padx=2)
            self.input_controls.append((preset_button, "normal"))
        tk.Label(controls, text="AWGN: lower Eb/N0 = stronger noise.\nRange: -10 to 20 dB. Type, slide or use a preset.",
                 bg=PANEL, fg=MUTED, wraplength=252, justify="left",
                 font=("Segoe UI", 9), anchor="w").pack(fill="x", pady=(4, 8))
        row = tk.Frame(controls, bg=PANEL)
        row.pack(fill="x")
        tk.Label(row, text="Noise seed", bg=PANEL, fg=TEXT).pack(side="left")
        self.seed = tk.IntVar(value=2026)
        seed = ttk.Spinbox(row, from_=0, to=2147483647, textvariable=self.seed, width=10)
        seed.pack(side="right")
        self.input_controls.append((seed, "normal"))
        self.no_noise = tk.BooleanVar(value=False)
        cb = ttk.Checkbutton(controls, text="No noise (verify exact recovery)", variable=self.no_noise)
        cb.pack(anchor="w", pady=(6, 0))
        self.input_controls.append((cb, "normal"))
        heading("03  ITERATION LIMITS")
        iteration_box = tk.Frame(controls, bg=PANEL)
        iteration_box.pack(fill="x")
        self.limits = {}
        for position, limit in enumerate([0, 1, 2, 3, 5, 10, 20]):
            variable = tk.BooleanVar(value=limit in [0, 1, 2, 5, 10, 20])
            self.limits[limit] = variable
            cb = ttk.Checkbutton(iteration_box, text=str(limit), variable=variable)
            cb.grid(row=position//4, column=position%4, sticky="w", padx=3, pady=2)
            self.input_controls.append((cb, "normal"))
        tk.Label(controls, text="0 = hard decision. Decoding stops early\nwhen parity checks pass; later results\nmay therefore be identical.",
                 bg=PANEL, fg=MUTED, justify="left", anchor="w",
                 font=("Segoe UI", 9)).pack(fill="x", pady=(5, 6))
        heading("04  FPGA CONNECTION")
        self.initialize = tk.BooleanVar(value=True)
        cb = ttk.Checkbutton(controls, text="Initialize board / load bitstream", variable=self.initialize)
        cb.pack(anchor="w")
        self.input_controls.append((cb, "normal"))
        self.probe_button = button("Check JTAG connection", self.check_connection)
        self.run_button = button("Run FPGA comparison", self.start_run, style="Primary.TButton")
        self.cancel_button = ttk.Button(controls, text="Cancel run", command=self.cancel_run, state="disabled")
        self.cancel_button.pack(fill="x", pady=3)
        ttk.Button(controls, text="Open results folder", command=self.open_folder).pack(fill="x", pady=(12, 3))
        tk.Label(controls, text="Connect board power and JTAG USB.\nUses local hw_server on port 3121.\nThe UART / COM port is not used.",
                 bg=PANEL, fg=MUTED, justify="left", anchor="w",
                 font=("Segoe UI", 9)).pack(fill="x", pady=8)

        right = tk.Frame(main, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        tk.Label(right, text="One image. One noise realization. Multiple iteration limits.",
                 bg=BG, fg=TEXT, font=("Segoe UI", 14, "bold"), anchor="w").pack(fill="x")
        self.summary_label = tk.Label(right, text="Choose an image, configure the channel, then run the FPGA.",
                                      bg=BG, fg=MUTED, anchor="w", justify="left")
        self.summary_label.pack(fill="x", pady=(5, 12))
        self.progress = ttk.Progressbar(right, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(0, 8))
        self.status = tk.StringVar(value="Ready. Decoded images are returned by the physical FPGA.")
        tk.Label(right, textvariable=self.status, bg=BG, fg=INK, anchor="w",
                 wraplength=980, justify="left").pack(fill="x", pady=(0, 10))
        gallery = tk.Frame(right, bg=BG)
        gallery.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(gallery, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(gallery, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.grid_frame = tk.Frame(self.canvas, bg=BG)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.grid_frame.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self.resize_gallery)
        self.bind("<MouseWheel>", self.wheel)
        tk.Label(right, text="FPGA time includes ARM control, TX/RX DMA and decoding. JTAG, image processing and display are excluded.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9), anchor="w").pack(fill="x", pady=(10, 0))

    def set_noise_db(self, value):
        self.db.set(f"{float(value):g}")
        self.db_slider_value.set(float(value))

    def on_noise_slide(self, value):
        self.db.set(f"{float(value):.1f}")

    def sync_noise_slider(self, event=None):
        try:
            value = float(self.db.get())
            if math.isfinite(value) and NOISE_DB_MIN <= value <= NOISE_DB_MAX:
                self.db_slider_value.set(value)
        except (ValueError, tk.TclError):
            pass

    def wheel(self, event):
        target = self.side_canvas if event.x_root - self.winfo_rootx() < 330 else self.canvas
        target.yview_scroll(int(-event.delta/120), "units")

    def resize_gallery(self, event=None):
        width = self.canvas.winfo_width()
        self.canvas.itemconfigure(self.canvas_window, width=width)
        columns = 3 if width >= 960 else 2 if width >= 600 else 1
        for i, card in enumerate(self.cards):
            card.grid(row=i//columns, column=i%columns, sticky="nsew", padx=5, pady=6)
        for c in range(3):
            self.grid_frame.columnconfigure(c, weight=1 if c < columns else 0, uniform="cards" if c < columns else "")

    def clear_cards(self):
        for card in self.cards:
            card.destroy()
        self.cards.clear()
        self.canvas.yview_moveto(0)

    def add_card(self, title, image, line1, line2="", accent=INK):
        card = tk.Frame(self.grid_frame, bg=CARD, highlightbackground="#d7d7d7", highlightthickness=1)
        tk.Label(card, text=title, bg=CARD, fg=accent, font=("Segoe UI", 11, "bold"),
                 anchor="w").pack(fill="x", padx=12, pady=(11, 8))
        thumb = image.copy()
        scale = min(280 / thumb.width, 210 / thumb.height)
        thumb = thumb.resize((max(1, round(thumb.width*scale)),
                              max(1, round(thumb.height*scale))), Image.Resampling.NEAREST)
        photo = ImageTk.PhotoImage(thumb)
        panel = tk.Label(card, image=photo, bg="#f7f7f7", height=210)
        panel.image = photo
        panel.pack(fill="x", padx=10)
        tk.Label(card, text=line1, bg=CARD, fg=TEXT, wraplength=290, justify="left",
                 anchor="w").pack(fill="x", padx=12, pady=(9, 3))
        tk.Label(card, text=line2, bg=CARD, fg=MUTED, wraplength=290, justify="left",
                 anchor="w", font=("Segoe UI", 9)).pack(fill="x", padx=12, pady=(0, 12))
        self.cards.append(card)
        self.resize_gallery()

    def browse(self):
        path = filedialog.askopenfilename(title="Choose an image for FPGA decoding",
                    filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff"), ("All files", "*.*")])
        if path:
            self.select_file(path)

    def select_file(self, path):
        if self.busy:
            return
        try:
            from PIL import ImageOps
            with Image.open(path) as source:
                preview = ImageOps.exif_transpose(source).convert("RGB")
                preview.thumbnail((1024, 768))
            self.file = Path(path)
            self.file_label.configure(text=self.file.name)
            self.clear_cards()
            self.add_card("Original image", preview, f"{preview.width} × {preview.height} RGB",
                          "Resized to the selected bounds when the run starts.")
            self.status.set("Image loaded. Adjust the noise level and iteration limits.")
        except Exception as exc:
            messagebox.showerror("Cannot open image", str(exc))

    def set_busy(self, busy):
        self.busy = busy
        for control, normal in self.input_controls:
            control.configure(state="disabled" if busy else normal)
        self.cancel_button.configure(state="normal" if busy else "disabled")
        if busy:
            self.progress["value"] = 0

    def check_connection(self):
        self.set_busy(True)
        self.cancel_button.configure(state="disabled")
        self.status.set("Checking JTAG / hw_server...")
        def worker():
            try:
                probe(lambda *_: None)
                self.events.put(("connection", "Cortex-A53 #0 detected. JTAG connection is ready."))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def start_run(self):
        if not self.file:
            self.browse()
            return
        try:
            limits = [n for n, selected in self.limits.items() if selected.get()]
            if not limits:
                raise ValueError("Select at least one iteration limit.")
            db, seed = parse_channel_settings(self.db.get(), self.seed.get())
            width = int(self.size.get().split(" × ")[0])
            params = (self.file, (width, width*3//4), db, seed,
                      self.no_noise.get(), limits, self.initialize.get())
        except Exception as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return
        self.cancel_event.clear()
        self.set_busy(True)
        self.status.set("Encoding image and generating one fixed noise realization...")
        self.result_count = 0
        self.total_results = len(limits)
        threading.Thread(target=self.worker, args=params, daemon=True).start()

    def worker(self, source, bound, db, seed, no_noise, limits, initialize):
        job = ROOT.parent / "results" / ("custom_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")) / DEMO_VERSION
        job.mkdir(parents=True)
        results = []
        manifest = {
            "hardware_version": DEMO_VERSION, "source_image": source.name, "ebn0_db": db, "noise_seed": seed,
            "no_noise": no_noise, "iteration_limits": limits, "completed": False,
            "channel": "BPSK AWGN; sigma^2=1/(2*(194/384)*10^(EbN0/10)); LLR clipped to +/-30",
            "decoder": "physical FPGA, float32 flooding NMS, alpha=.75, early termination",
            "fpga_dma_timing_includes": "ARM control, sequential RX/TX DMA, FPGA decoding, polling",
            "fpga_dma_timing_excludes": "JTAG upload/readback, image conversion, result packing, validation, GUI",
        }
        try:
            data = prepare_image(source, self.codec, bound, db, seed, no_noise)
            data.image.save(job / "original.png")
            data.received.save(job / "received.png")
            data.encoded.tofile(job / "encoded_tx.u8")
            manifest.update(width=data.image.width, height=data.image.height,
                            codewords=len(data.llr), payload_bits=int(data.payload_bits.size),
                            sigma=data.sigma)
            self.events.put(("prepared", (data, job)))
            def event(kind, payload):
                if kind == "result":
                    limit, path, report = payload
                    words = np.fromfile(path, dtype=np.uint8).reshape(-1, 384)
                    image, metrics = evaluate(self.codec, data, words)
                    image.save(job / f"iteration_{limit}.png")
                    result = dict(report, **metrics)
                    results.append(result)
                    manifest["results"] = results
                    (job / "results.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
                    self.events.put(("image_result", (limit, image, result)))
                else:
                    self.events.put((kind, payload))
            wall = run_hardware(data.llr, limits, job, initialize, event, self.cancel_event)
            manifest.update(completed=True, host_jtag_and_control_wall_s=wall, results=results)
            (job / "results.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
            keys = ["iteration_limit", "frames", "payload_bit_errors", "payload_ber", "psnr_db",
                    "unsatisfied_frames", "fpga_dma_ms", "mean_actual_iterations", "max_actual_iterations"]
            with (job / "results.csv").open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(results)
            self.events.put(("finished", (job, wall)))
        except Cancelled:
            manifest.update(cancelled=True, results=results)
            (job / "results.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
            self.events.put(("cancelled", "Run cancelled. Completed results remain in the output folder."))
        except Exception as exc:
            manifest.update(error=str(exc), results=results)
            (job / "results.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
            self.events.put(("error", str(exc)))

    def poll_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "prepared":
                    data, folder = payload
                    self.last_folder = folder
                    self.clear_cards()
                    self.add_card("Original image / Reference", data.image, "Before channel transmission", "BER and PSNR use this resized RGB image as the reference.", "#111111")
                    _, metrics = evaluate(self.codec, data, (data.llr < 0).astype(np.uint8))
                    self.add_card("Channel output / No decoding", data.received,
                                  f"Payload bit errors {metrics['payload_bit_errors']:,}  |  BER {metrics['payload_ber']:.3e}",
                                  "BPSK + AWGN followed by hard decisions and payload extraction.", "#111111")
                    self.summary_label.configure(text=f"{data.image.width} × {data.image.height} RGB  ·  {len(data.llr):,} codewords  ·  N=384 / K=194  ·  Eb/N₀={data.ebn0_db:g} dB  ·  seed={data.seed}")
                elif kind == "stage":
                    self.status.set(str(payload))
                elif kind == "progress":
                    pass
                elif kind == "image_result":
                    limit, image, result = payload
                    self.result_count += 1
                    self.progress["value"] = 100 * self.result_count / self.total_results
                    psnr = "∞" if result["exact_image"] else f"{result['psnr_db']:.2f}"
                    self.add_card(f"FPGA / Iteration limit {limit}", image,
                        f"Errors {result['payload_bit_errors']:,} bits  |  BER {result['payload_ber']:.3e}\nPSNR {psnr} dB  |  FPGA + DMA {result['fpga_dma_ms']:.3f} ms",
                        f"Actual mean {result['mean_actual_iterations']:.2f} iterations / max {result['max_actual_iterations']}  iterations\nUnsatisfied checks: {result['unsatisfied_frames']:,} codewords")
                elif kind == "finished":
                    folder, wall = payload
                    self.last_folder = folder
                    self.set_busy(False)
                    self.progress["value"] = 100
                    self.status.set(f"Completed {self.result_count} FPGA comparisons. Host / JTAG wall time: {wall:.1f} s. Images and CSV saved.")
                elif kind == "connection":
                    self.set_busy(False)
                    self.status.set(payload)
                elif kind == "cancelled":
                    self.set_busy(False)
                    self.status.set(payload)
                elif kind == "error":
                    self.set_busy(False)
                    self.status.set("Run failed. Check board power, JTAG and hw_server.")
                    messagebox.showerror("FPGA operation failed", str(payload))
        except queue.Empty:
            pass
        self.after(80, self.poll_events)

    def cancel_run(self):
        self.cancel_event.set()
        (self.last_folder / "cancel.flag").touch(exist_ok=True)
        self.status.set("Cancellation requested. Waiting for the current JTAG transfer or codeword...")

    def open_folder(self):
        self.last_folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(self.last_folder))

    def close_app(self):
        if self.busy:
            self.cancel_event.set()
        self.destroy()

if __name__ == "__main__":
    App().mainloop()
