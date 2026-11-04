"""Shared look of the FPGA Image Lab (same style as app_custom.py):
left sidebar with numbered sections, right gallery with one card per image
(original, channel output, then one card per FPGA iteration limit).
"""
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk

BG, PANEL, CARD, TEXT, MUTED, INK = "#ffffff", "#f3f3f3", "#ffffff", "#111111", "#666666", "#111111"
GOOD, BAD = "#11753a", "#b00020"

STARTUP_MODES = {
    "Automatic: reset + bitstream + FSBL": dict(attach=False, initialize=True),
    "Firmware only (bitstream already loaded)": dict(attach=False, initialize=False),
    "Attach to Vitis Run (no reset)": dict(attach=True, initialize=False),
}


def apply_style(root):
    root.option_add("*TCombobox*Listbox.background", "#ffffff")
    root.option_add("*TCombobox*Listbox.foreground", "#111111")
    root.option_add("*TCombobox*Listbox.selectBackground", "#111111")
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=("Segoe UI", 10), background=PANEL, foreground=TEXT)
    style.configure("TButton", padding=(12, 8), background="#ffffff", foreground=TEXT,
                    bordercolor="#cccccc", lightcolor="#ffffff", darkcolor="#cccccc", borderwidth=1)
    style.map("TButton", background=[("active", "#e5e5e5"), ("disabled", "#eeeeee")],
              foreground=[("disabled", "#999999")])
    style.configure("Primary.TButton", background="#111111", foreground="#ffffff",
                    font=("Segoe UI", 11, "bold"), padding=(16, 13))
    style.map("Primary.TButton", background=[("disabled", "#bbbbbb"), ("active", "#333333")],
              foreground=[("disabled", "#ffffff"), ("active", "#ffffff")])
    style.configure("TCheckbutton", background=PANEL, foreground=TEXT, padding=4)
    style.map("TCheckbutton", background=[("active", PANEL)])
    style.configure("TCombobox", fieldbackground="#ffffff", foreground=TEXT, padding=5)
    style.map("TCombobox", fieldbackground=[("readonly", "#ffffff")],
              selectbackground=[("readonly", "#ffffff")], selectforeground=[("readonly", TEXT)])
    style.configure("TProgressbar", background=INK, troughcolor="#e2e2e2", borderwidth=0)
    style.configure("Vertical.TScrollbar", background="#e2e2e2", troughcolor="#f5f5f5",
                    bordercolor="#cccccc", arrowcolor="#333333", lightcolor="#ffffff", darkcolor="#bbbbbb")
    style.map("Vertical.TScrollbar", background=[("active", "#cccccc")])


class LabLayout:
    """Builds the sidebar + gallery inside `root` (a Tk or Toplevel)."""

    def __init__(self, root, title, subtitle, badge, headline):
        self.root = root
        self.cards, self.input_controls = [], []
        root.configure(bg=BG)
        apply_style(root)
        header = tk.Frame(root, bg=BG); header.pack(fill="x", padx=26, pady=(20, 14))
        tk.Label(header, text=title, bg=BG, fg=TEXT, font=("Segoe UI", 23, "bold")).pack(side="left")
        tk.Label(header, text="  " + subtitle, bg=BG, fg=MUTED, font=("Segoe UI", 11)).pack(side="left", padx=12)
        tk.Label(header, text=badge, bg="#111111", fg="#ffffff", font=("Segoe UI", 10, "bold"),
                 padx=12, pady=7).pack(side="right")
        main = tk.Frame(root, bg=BG); main.pack(fill="both", expand=True, padx=24, pady=(0, 18))

        sidebar = tk.Frame(main, bg=PANEL, width=310); sidebar.pack(side="left", fill="y", padx=(0, 18))
        sidebar.pack_propagate(False)
        self.side_canvas = tk.Canvas(sidebar, bg=PANEL, highlightthickness=0)
        side_scroll = ttk.Scrollbar(sidebar, orient="vertical", command=self.side_canvas.yview)
        side_scroll.pack(side="right", fill="y")
        self.side_canvas.configure(yscrollcommand=side_scroll.set)
        self.side_canvas.pack(side="left", fill="both", expand=True)
        self.controls = tk.Frame(self.side_canvas, bg=PANEL)
        window = self.side_canvas.create_window((16, 12), window=self.controls, anchor="nw")
        self.controls.bind("<Configure>", lambda _: self.side_canvas.configure(scrollregion=self.side_canvas.bbox("all")))
        self.side_canvas.bind("<Configure>", lambda e: self.side_canvas.itemconfigure(window, width=e.width - 28))

        right = tk.Frame(main, bg=BG); right.pack(side="left", fill="both", expand=True)
        tk.Label(right, text=headline, bg=BG, fg=TEXT, font=("Segoe UI", 14, "bold"), anchor="w").pack(fill="x")
        self.summary_label = tk.Label(right, text="", bg=BG, fg=MUTED, anchor="w", justify="left", wraplength=980)
        self.summary_label.pack(fill="x", pady=(5, 12))
        self.progress = ttk.Progressbar(right, mode="determinate", maximum=100); self.progress.pack(fill="x", pady=(0, 8))
        self.status = tk.StringVar(value="Ready.")
        tk.Label(right, textvariable=self.status, bg=BG, fg=INK, anchor="w", wraplength=980,
                 justify="left").pack(fill="x", pady=(0, 10))
        gallery = tk.Frame(right, bg=BG); gallery.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(gallery, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(gallery, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y"); self.canvas.pack(side="left", fill="both", expand=True)
        self.grid_frame = tk.Frame(self.canvas, bg=BG)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.grid_frame.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self.resize_gallery)
        root.bind("<MouseWheel>", self.wheel)
        self.footer = tk.Label(right, text="", bg=BG, fg=MUTED, font=("Segoe UI", 9), anchor="w", justify="left")
        self.footer.pack(fill="x", pady=(10, 0))

    # ----- sidebar helpers -----
    def heading(self, text):
        tk.Label(self.controls, text=text, bg=PANEL, fg=INK, font=("Segoe UI", 11, "bold"),
                 anchor="w").pack(fill="x", pady=(10, 8))

    def note(self, text):
        label = tk.Label(self.controls, text=text, bg=PANEL, fg=MUTED, justify="left", anchor="w",
                         wraplength=262, font=("Segoe UI", 9))
        label.pack(fill="x", pady=(4, 6))
        return label

    def button(self, text, command, **options):
        b = ttk.Button(self.controls, text=text, command=command, **options)
        b.pack(fill="x", pady=3); self.input_controls.append((b, "normal"))
        return b

    def combo(self, variable, values, label=None):
        if label:
            tk.Label(self.controls, text=label, bg=PANEL, fg=TEXT, anchor="w").pack(fill="x")
        c = ttk.Combobox(self.controls, textvariable=variable, values=values, state="readonly")
        c.pack(fill="x", pady=(4, 8)); self.input_controls.append((c, "readonly"))
        return c

    def iteration_boxes(self, choices, default):
        box = tk.Frame(self.controls, bg=PANEL); box.pack(fill="x")
        variables = {}
        for position, limit in enumerate(choices):
            v = tk.BooleanVar(value=limit in default); variables[limit] = v
            cb = ttk.Checkbutton(box, text=str(limit), variable=v)
            cb.grid(row=position // 4, column=position % 4, sticky="w", padx=3, pady=2)
            self.input_controls.append((cb, "normal"))
        self.note("0 = hard decision (no LDPC). Each codeword stops early when its parity checks pass, so later results may be identical.")
        return variables

    def startup_selector(self):
        self.startup = tk.StringVar(value=next(iter(STARTUP_MODES)))
        self.combo(self.startup, list(STARTUP_MODES), "Board start-up")
        self.note("Attach: start the matching v1/v2/v3 configuration with Vitis Run first; the board is not reset.")

    def startup_mode(self):
        return STARTUP_MODES[self.startup.get()]

    # ----- gallery -----
    def wheel(self, event):
        target = self.side_canvas if event.x_root - self.root.winfo_rootx() < 340 else self.canvas
        target.yview_scroll(int(-event.delta / 120), "units")

    def resize_gallery(self, event=None):
        width = self.canvas.winfo_width()
        self.canvas.itemconfigure(self.canvas_window, width=width)
        columns = 3 if width >= 960 else 2 if width >= 600 else 1
        for i, card in enumerate(self.cards):
            card.grid(row=i // columns, column=i % columns, sticky="nsew", padx=5, pady=6)
        for c in range(3):
            self.grid_frame.columnconfigure(c, weight=1 if c < columns else 0, uniform="cards" if c < columns else "")

    def clear_cards(self):
        for card in self.cards:
            card.destroy()
        self.cards.clear(); self.canvas.yview_moveto(0)

    def add_card(self, title, image, line1, line2="", accent=INK):
        card = tk.Frame(self.grid_frame, bg=CARD, highlightbackground="#d7d7d7", highlightthickness=1)
        tk.Label(card, text=title, bg=CARD, fg=accent, font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x", padx=12, pady=(11, 8))
        thumb = image.copy() if isinstance(image, Image.Image) else Image.fromarray(image)
        scale = min(280 / thumb.width, 210 / thumb.height)
        thumb = thumb.resize((max(1, round(thumb.width * scale)), max(1, round(thumb.height * scale))), Image.Resampling.NEAREST)
        photo = ImageTk.PhotoImage(thumb)
        panel = tk.Label(card, image=photo, bg="#f7f7f7", height=210); panel.image = photo; panel.pack(fill="x", padx=10)
        tk.Label(card, text=line1, bg=CARD, fg=TEXT, wraplength=290, justify="left", anchor="w").pack(fill="x", padx=12, pady=(9, 3))
        tk.Label(card, text=line2, bg=CARD, fg=MUTED, wraplength=290, justify="left", anchor="w",
                 font=("Segoe UI", 9)).pack(fill="x", padx=12, pady=(0, 12))
        self.cards.append(card); self.resize_gallery()

    def set_busy(self, busy, cancel_button=None):
        self.busy = busy
        for control, normal in self.input_controls:
            control.configure(state="disabled" if busy else normal)
        if cancel_button is not None:
            cancel_button.configure(state="normal" if busy else "disabled")
        if busy:
            self.progress["value"] = 0
