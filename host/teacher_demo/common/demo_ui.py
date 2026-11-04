"""Fixed teammate LLR on the Kria FPGA, same layout as the Custom Image UI:
one card per FPGA iteration limit. Uses the verified run_case pipeline
(manifest integrity checks, dataset reference comparison at 20 iterations).
"""
from datetime import datetime
import argparse, os, queue, threading, tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image
import numpy as np
import fpga_bridge as bridge
import demo_runner
from codec import Codec, reconstruct
from demo_runner import ROOT, DATASET, cases, configure, run_case, BoardLock
from lab_ui import LabLayout, GOOD, BAD, INK

LIMITS = [0, 1, 2, 3, 5, 10, 20]


class FixedLab:
    def __init__(self, root, version):
        self.root = root
        self.items = cases(); self.events = queue.Queue(); self.cancel = threading.Event()
        self.busy = False; self.folder = ROOT / 'results'; self.count = 0; self.total = 0
        self.codec = Codec()
        ui = self.ui = LabLayout(root, 'LDPC FPGA Fixed-LLR Lab', 'Teammate AWGN 3 dB LLR → NMS → AXI DMA',
                                 'HARDWARE MODE', 'One fixed noisy input. Multiple FPGA iteration limits.')
        ui.footer.configure(text='FPGA time includes ARM control, TX/RX DMA and decoding. Dataset loading, '
                                 'JTAG, image rendering and display are excluded.\nOriginal float32 teammate LLR, '
                                 'copied byte-for-byte; no regenerated noise.')

        ui.heading('01  FIXED TEAMMATE LLR')
        self.case = tk.StringVar(value=self.items[0]['id'])
        box = ui.combo(self.case, [c['id'] for c in self.items], 'Dataset case (256 × 192, Eb/N0 3 dB)')
        box.bind('<<ComboboxSelected>>', lambda _: self.preview())

        ui.heading('02  HARDWARE')
        self.version = tk.StringVar(value=version)
        ui.combo(self.version, ['v1', 'v2', 'v3'], 'Decoder version on the Kria PL')

        ui.heading('03  ITERATION LIMITS')
        self.limits = ui.iteration_boxes(LIMITS, [0, 1, 2, 5, 10, 20])

        ui.heading('04  FPGA CONNECTION')
        ui.startup_selector()
        ui.button('Check JTAG connection', self.check_connection)
        self.run_button = ui.button('Run FPGA comparison', self.start, style='Primary.TButton')
        self.cancel_button = ttk.Button(ui.controls, text='Cancel run', command=self.cancel_run, state='disabled')
        self.cancel_button.pack(fill='x', pady=3)
        ttk.Button(ui.controls, text='Open results folder', command=self.open_folder).pack(fill='x', pady=(12, 3))
        ui.button('ZCU111 ADC capture...', self.open_adc)
        ui.note('Close Vitis debug sessions and other board UIs before running. Uses local hw_server on port 3121.')
        self.preview()
        self.root.after(80, self.poll)

    def selected_case(self):
        return next(c for c in self.items if c['id'] == self.case.get())

    def preview(self):
        if self.busy:
            return
        c = self.selected_case(); ui = self.ui
        with Image.open(DATASET / c['image']) as im:
            original = im.convert('RGB')
        llr = np.fromfile(DATASET / c['llr'], dtype='<f4').reshape(-1, 384)
        hard = (llr < 0).astype('u1')
        bits = np.unpackbits(np.asarray(original, dtype='u1').reshape(-1), bitorder='big')
        errors = int(np.count_nonzero(self.codec.payload(hard, bits.size) != bits))
        ui.clear_cards()
        ui.add_card('Original image / Reference', original, f'{original.width} × {original.height} RGB',
                    f'{bits.size:,} payload bits → {len(llr):,} LDPC(384,194) codewords.')
        ui.add_card('Channel output / No decoding', reconstruct(self.codec, hard, original.size),
                    f'Payload bit errors {errors:,}  |  BER {errors / bits.size:.3e}',
                    'Teammate fixed float32 LLR (AWGN Eb/N0 3 dB), hard decisions only.', BAD)
        ui.summary_label.configure(text=f'{c["id"]}  ·  {original.width} × {original.height} RGB  ·  {len(llr):,} codewords  ·  '
                                        f'N=384 / K=194  ·  Eb/N₀ 3 dB  ·  fixed teammate LLR')
        ui.status.set('Ready. Choose the hardware version and iteration limits, then run the FPGA.')

    def prepare_hardware(self):
        mode = self.ui.startup_mode()
        demo_runner.ATTACH_RUNNING = mode['attach']  # read by configure()
        configure(self.version.get())
        return mode

    def check_connection(self):
        try:
            self.prepare_hardware()
        except Exception as exc:
            messagebox.showerror('Hardware', str(exc)); return
        self.busy = True; self.ui.set_busy(True, None); self.ui.status.set('Checking JTAG / hw_server...')

        def worker():
            try:
                bridge.probe(lambda *_: None)
                self.events.put(('connection', 'Cortex-A53 #0 detected. JTAG connection is ready.'))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def start(self):
        limits = sorted(n for n, v in self.limits.items() if v.get())
        if not limits:
            messagebox.showerror('Iteration limits', 'Select at least one iteration limit.'); return
        try:
            mode = self.prepare_hardware()
        except Exception as exc:
            messagebox.showerror('Hardware', str(exc)); return
        version, case = self.version.get(), self.selected_case()
        self.folder = ROOT / 'results' / ('ui_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f')) / version / case['id']
        self.preview()
        self.cancel.clear(); self.busy = True; self.ui.set_busy(True, self.cancel_button)
        self.count, self.total = 0, len(limits)
        self.ui.status.set(f'{version}: starting the FPGA ({self.ui.startup.get()}).')

        def worker():
            try:
                with BoardLock():
                    run_case(version, case, limits, self.folder, False, mode['initialize'],
                             lambda k, m: self.events.put((k, m)), self.cancel)
                self.events.put(('done', str(self.folder)))
            except bridge.Cancelled:
                self.events.put(('cancelled', 'Run cancelled. Completed results remain in the output folder.'))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        ui = self.ui
        try:
            while True:
                kind, msg = self.events.get_nowait()
                if kind == 'sample':
                    r = msg['record']
                    self.count += 1; ui.progress['value'] = 100 * self.count / max(self.total, 1)
                    with Image.open(msg['image']) as im:
                        image = im.convert('RGB')
                    psnr = '∞' if r.get('exact_image') else f"{r['psnr_db']:.2f}"
                    ref = r.get('dataset_reference_bit_mismatches')
                    ref_text = 'teammate reference: compared at limit 20' if ref is None else f'teammate reference mismatches: {ref} bits'
                    ui.add_card(f"FPGA {r['version']} / Iteration limit {r['iteration_limit']}", image,
                                f"Errors {r['payload_bit_errors']:,} bits  |  BER {r['payload_ber']:.3e}\n"
                                f"PSNR {psnr} dB  |  FPGA + DMA {r['fpga_dma_ms']:.3f} ms",
                                f"Actual mean {r['mean_actual_iterations']:.2f} iterations / max {r['max_actual_iterations']}\n"
                                f"Unsatisfied checks: {r['unsatisfied_frames']:,} codewords  |  {ref_text}",
                                GOOD if r.get('exact_image') else INK)
                elif kind == 'stage':
                    ui.status.set(str(msg))
                elif kind == 'done':
                    self.finish(f'Completed {self.count} FPGA runs. Saved: {msg}')
                elif kind in ('connection', 'cancelled'):
                    self.finish(str(msg))
                elif kind == 'error':
                    self.finish('Run failed. Check board power, JTAG, hw_server and the start-up mode.')
                    messagebox.showerror('FPGA operation failed', str(msg))
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

    def finish(self, text):
        self.busy = False; self.ui.set_busy(False, self.cancel_button); self.ui.status.set(text)
        if self.count and self.count == self.total:
            self.ui.progress['value'] = 100

    def cancel_run(self):
        self.cancel.set()
        self.ui.status.set('Cancellation requested. Waiting for the current JTAG transfer or codeword...')

    def open_folder(self):
        self.folder.mkdir(parents=True, exist_ok=True); os.startfile(str(self.folder))

    def open_adc(self):
        if self.busy:
            messagebox.showinfo('FPGA running', 'Wait for the current run to finish first.'); return
        import adc_ui
        adc_ui.open_window(self.root, self.version.get())


class App(tk.Tk):
    """Kept for compatibility: demo_ui.App(version)."""
    def __init__(self, version='v3'):
        super().__init__()
        self.title(f'LDPC {version} | Fixed teammate LLR'); self.geometry('1440x960'); self.minsize(1080, 740)
        self.lab = FixedLab(self, version)
        self.protocol('WM_DELETE_WINDOW', self.close)

    def close(self):
        if self.lab.busy:
            messagebox.showinfo('FPGA running', 'Wait for the current run to finish before closing.'); return
        self.destroy()


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--version', default='v3', choices=['v1', 'v2', 'v3']); a = p.parse_args()
    App(a.version).mainloop()
