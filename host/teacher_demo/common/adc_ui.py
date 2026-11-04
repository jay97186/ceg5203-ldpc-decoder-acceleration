"""ZCU111 ADC capture -> LLR (PC receiver) -> LDPC decoding on the Kria FPGA (v1/v2/v3).

Same layout as the Custom Image UI: one card per FPGA iteration limit.
The capture is a TDMS file exported from the RF Data Converter Evaluation UI
(File -> Export ADC Data to TDMS). The PC only synchronizes, demodulates and
computes LLRs; every decoded card comes from the physical FPGA via AXI DMA.
The PC float32 NMS decoder runs alongside only to check bit-exactness.
"""
from pathlib import Path
from datetime import datetime
import argparse, csv, json, os, queue, threading, tkinter as tk
from tkinter import ttk, messagebox, filedialog
import numpy as np

import fpga_bridge as bridge
import demo_runner
from demo_runner import ROOT, configure, BoardLock
import zcu111_rx as rx
from lab_ui import LabLayout, GOOD, BAD, INK

ADC_DIR = Path(r'C:\Xilinx\RF_DC_Evaluation_UI\Data\ADC')
LIMITS = [0, 1, 2, 3, 5, 10, 15, 20]


class AdcLab:
    def __init__(self, root, version='v3'):
        self.root = root
        self.events = queue.Queue(); self.cancel = threading.Event()
        self.busy = False; self.data = None; self.capture = None
        self.folder = ROOT / 'results'; self.count = 0; self.total = 0
        ui = self.ui = LabLayout(root, 'LDPC FPGA ADC Lab', 'ZCU111 DAC → SMA → ADC → NMS → AXI DMA',
                                 'HARDWARE MODE', 'One real ADC capture. Multiple FPGA iteration limits.')
        ui.summary_label.configure(text='Choose a ZCU111 ADC capture, check the receiver, then run the FPGA.')
        ui.footer.configure(text='FPGA time includes ARM control, TX/RX DMA and decoding. The PC receiver (sync, '
                                 'demodulation, LLR), JTAG and display are excluded.\nErrors are counted against the '
                                 'transmitted codewords, which are never used for decoding.')

        ui.heading('01  ADC CAPTURE')
        ui.button('Choose capture (.tdms)...', self.browse)
        self.file_label = ui.note('No capture selected')
        self.waveform = tk.StringVar(value='QPSK 30x30')
        wbox = ui.combo(self.waveform, list(rx.WAVEFORMS), 'Transmitted waveform')
        wbox.bind('<<ComboboxSelected>>', lambda _: self.load_capture() if self.capture else None)
        ui.note('QPSK 30x30 = photo30q_all_qpsk_407p04MHz\nBPSK 20x20 = photo20_all_bpsk_407p04MHz')

        ui.heading('02  HARDWARE')
        self.version = tk.StringVar(value=version)
        ui.combo(self.version, ['v1', 'v2', 'v3'], 'Decoder version on the Kria PL')

        ui.heading('03  ITERATION LIMITS')
        self.limits = ui.iteration_boxes(LIMITS, [0, 1, 2, 3, 5, 10, 15, 20])

        ui.heading('04  FPGA CONNECTION')
        ui.startup_selector()
        ui.button('Check JTAG connection', self.check_connection)
        self.run_button = ui.button('Run FPGA comparison', self.start, style='Primary.TButton')
        self.cancel_button = ttk.Button(ui.controls, text='Cancel run', command=self.cancel_run, state='disabled')
        self.cancel_button.pack(fill='x', pady=3)
        ttk.Button(ui.controls, text='Open results folder', command=self.open_folder).pack(fill='x', pady=(12, 3))
        ui.note('Close Vitis debug sessions and other board UIs before running. Uses local hw_server on port 3121.')
        self.root.after(80, self.poll)

    # ---------- capture ----------
    def browse(self):
        start = ADC_DIR if ADC_DIR.is_dir() else Path.home()
        path = filedialog.askopenfilename(parent=self.root, title='ZCU111 ADC capture', initialdir=start,
                                          filetypes=[('TDMS capture', '*.tdms'), ('All files', '*.*')])
        if path:
            self.select(path)

    def select(self, path):
        if self.busy:
            return
        self.capture = Path(path)
        self.file_label.configure(text=self.capture.name)
        self.waveform.set(rx.guess_waveform(path))
        self.load_capture()

    def load_capture(self):
        try:
            data = rx.receive(self.capture, self.waveform.get())
        except Exception as exc:
            messagebox.showerror('ADC capture', str(exc), parent=self.root); self.data = None; return False
        ref, manifest = data['ref'], data['manifest']
        raw_img, raw_ok, raw_note = rx.decode_image(data['hard'], manifest, ref)
        self.data = dict(data, capture=str(self.capture), raw_image=raw_img)
        words = ref['words']; ui = self.ui
        ui.clear_cards()
        h, w = ref['pixels'].shape
        ui.add_card('Transmitted image / Reference', ref['pixels'], f'{w} × {h}, 4 grey tones, {data["kind"]}',
                    f'Huffman + CRC-16 → {len(words)} LDPC(384,194) codewords → {words.size} coded bits.')
        ui.add_card('ADC capture / No decoding', raw_img,
                    f'Channel bit errors {data["channel_bit_errors"]:,} / {words.size:,}  |  BER {data["channel_bit_errors"] / words.size:.3e}\n'
                    f'Image: {raw_note}',
                    f'SNR {data["snr_db"]:.1f} dB  |  preamble errors {data["preamble_bit_errors"]}/48, '
                    f'correlation {data["preamble_correlation"]:.3f}  |  ADC peak {data["peak_abs_adc"]:.0f}',
                    BAD if data['channel_bit_errors'] else INK)
        ui.summary_label.configure(text=f'{self.capture.name}  ·  {data["waveform"]}  ·  {len(words)} codewords  ·  '
                                        f'N=384 / K=194  ·  SNR {data["snr_db"]:.1f} dB  ·  real channel, no simulated noise')
        if data['preamble_bit_errors'] > 10:
            ui.status.set('WARNING: many preamble errors — wrong waveform selected, or the capture has no signal.')
        else:
            ui.status.set('Capture loaded. Choose the hardware version and iteration limits, then run the FPGA.')
        return True

    # ---------- FPGA ----------
    def prepare_hardware(self):
        mode = self.ui.startup_mode()
        demo_runner.ATTACH_RUNNING = mode['attach']  # read by configure()
        configure(self.version.get())
        return mode

    def check_connection(self):
        try:
            self.prepare_hardware()
        except Exception as exc:
            messagebox.showerror('Hardware', str(exc), parent=self.root); return
        self.ui.set_busy(True, None); self.busy = True
        self.ui.status.set('Checking JTAG / hw_server...')

        def worker():
            try:
                bridge.probe(lambda *_: None)
                self.events.put(('connection', 'Cortex-A53 #0 detected. JTAG connection is ready.'))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def start(self):
        if self.capture is None:
            self.browse(); return
        if self.data is None or self.data.get('waveform') != self.waveform.get():
            if not self.load_capture():
                return
        limits = [n for n, v in self.limits.items() if v.get()]
        if not limits:
            messagebox.showerror('Iteration limits', 'Select at least one iteration limit.', parent=self.root); return
        try:
            mode = self.prepare_hardware()
        except Exception as exc:
            messagebox.showerror('Hardware', str(exc), parent=self.root); return
        data, version = self.data, self.version.get()
        self.startup_text = self.ui.startup.get()  # read Tk state here, never in the worker thread
        self.folder = ROOT / 'results' / ('adc_' + datetime.now().strftime('%Y%m%d_%H%M%S')) / version / self.capture.stem
        self.folder.mkdir(parents=True)
        self.save_inputs(data, version, mode)
        self.cancel.clear(); self.busy = True; self.ui.set_busy(True, self.cancel_button)
        self.count, self.total = 0, len(limits)
        while len(self.ui.cards) > 2:
            self.ui.cards.pop().destroy()
        self.ui.resize_gallery()
        self.ui.status.set(f'{version}: starting the FPGA ({self.ui.startup.get()}).')
        rows = []

        def relay(kind, message):
            if kind != 'result':
                self.events.put((kind, message)); return
            limit, path, report = message
            row, img = self.evaluate(data, limit, path, report, version)
            rows.append(row); self.write_csv(rows)
            self.events.put(('result', (row, img)))

        def worker():
            try:
                with BoardLock():
                    wall = bridge.run_hardware(data['llr'], limits, self.folder / 'transport',
                                               mode['initialize'], relay, self.cancel)
                self.events.put(('done', wall))
            except bridge.Cancelled:
                self.events.put(('cancelled', 'Run cancelled. Completed results remain in the output folder.'))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def save_inputs(self, data, version, mode):
        ref = data['ref']
        info = {k: v for k, v in data.items() if k not in ('llr', 'hard', 'ref', 'manifest', 'raw_image')}
        info.update(hardware_version=version, startup=self.startup_text, attach_running=mode['attach'],
                    codewords=int(len(ref['words'])), coded_bits=int(ref['words'].size),
                    decoder='physical Kria FPGA via AXI DMA (float32 flooding NMS, alpha 0.75, per-codeword early stop)',
                    receiver='PC: band filter, preamble sync, soft symbols, LLR clipped to +-30',
                    huffman_header_sent=data['manifest']['huffman'].get('header_sent', True))
        (self.folder / 'capture_info.json').write_text(json.dumps(info, indent=2), encoding='utf-8')
        data['llr'].astype('<f4').tofile(self.folder / 'input_llr.f32')
        self.big(ref['pixels']).save(self.folder / 'transmitted.png')
        self.big(data['raw_image']).save(self.folder / 'received_no_ldpc.png')

    @staticmethod
    def big(pixels, side=300):
        from PIL import Image
        return Image.fromarray(pixels).resize((side, side), Image.Resampling.NEAREST)

    def evaluate(self, data, limit, path, report, version):
        ref, manifest = data['ref'], data['manifest']
        words_ref = ref['words']
        raw = np.fromfile(path, dtype=np.uint8)
        if raw.size != words_ref.size or np.any(raw > 1):
            raise RuntimeError(f'Unexpected FPGA output size/content: {raw.size} bytes')
        words = raw.reshape(words_ref.shape)
        img, ok, note = rx.decode_image(words, manifest, ref)
        pc = rx.CODEC.reference(data['llr'], limit)
        bits = rx.CODEC.payload(words, len(ref['payload_bits']))
        (self.folder / f'decoded_limit_{limit}.u8').write_bytes(raw.tobytes())
        self.big(img).save(self.folder / f'fpga_decoded_limit_{limit}.png')
        row = dict(hardware_version=version, iteration_limit=limit, fpga_dma_ms=report['fpga_dma_ms'],
                   remaining_bit_errors=int(np.count_nonzero(words != words_ref)),
                   payload_bit_errors=int(np.count_nonzero(bits != ref['payload_bits'])),
                   unconverged_codewords=rx.CODEC.unsatisfied(words), crc_ok=bool(ok), image=note,
                   pixel_errors=int(np.count_nonzero(img != ref['pixels'])),
                   mean_actual_iterations=report['mean_actual_iterations'],
                   max_actual_iterations=report['max_actual_iterations'],
                   fpga_vs_pc_nms_bit_mismatches=int(np.count_nonzero(words != pc)),
                   channel_bit_errors=data['channel_bit_errors'], snr_db=data['snr_db'],
                   capture=data['capture'], waveform=data['waveform'], startup=self.startup_text)
        return row, img

    def write_csv(self, rows):
        with (self.folder / 'runs.csv').open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

    def poll(self):
        ui = self.ui
        try:
            while True:
                kind, msg = self.events.get_nowait()
                if kind == 'result':
                    row, img = msg
                    self.count += 1; ui.progress['value'] = 100 * self.count / max(self.total, 1)
                    crc = 'CRC OK — image exact' if row['crc_ok'] else row['image']
                    ui.add_card(f"FPGA {row['hardware_version']} / Iteration limit {row['iteration_limit']}", img,
                                f"Remaining errors {row['remaining_bit_errors']:,} bits  |  payload {row['payload_bit_errors']:,} bits\n"
                                f"{crc}  |  FPGA + DMA {row['fpga_dma_ms']:.3f} ms",
                                f"Actual mean {row['mean_actual_iterations']:.2f} iterations / max {row['max_actual_iterations']}\n"
                                f"Unconverged codewords {row['unconverged_codewords']}  |  FPGA vs PC NMS {row['fpga_vs_pc_nms_bit_mismatches']} bits",
                                GOOD if row['crc_ok'] else INK)
                elif kind == 'stage':
                    ui.status.set(str(msg))
                elif kind == 'done':
                    self.finish(f'Completed {self.count} FPGA runs. Host / JTAG wall time: {msg:.1f} s. Saved: {self.folder}')
                elif kind in ('connection', 'cancelled'):
                    self.finish(str(msg))
                elif kind == 'error':
                    self.finish('Run failed. Check board power, JTAG, hw_server and the start-up mode.')
                    messagebox.showerror('FPGA operation failed', str(msg), parent=self.root)
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


def open_window(master, version):
    """Open the ADC lab as a second window of an existing Tk app."""
    top = tk.Toplevel(master)
    top.title('LDPC FPGA | ZCU111 ADC capture'); top.geometry('1440x960'); top.minsize(1080, 740)
    lab = AdcLab(top, version)

    def close():
        if lab.busy:
            messagebox.showinfo('FPGA running', 'Wait for the current run to finish before closing.', parent=top); return
        top.destroy()
    top.protocol('WM_DELETE_WINDOW', close)
    return top


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--version', default='v3', choices=['v1', 'v2', 'v3'])
    p.add_argument('--capture', default=None, help='optional TDMS capture to load at start')
    a = p.parse_args()
    root = tk.Tk(); root.title(f'LDPC {a.version} | ZCU111 ADC capture'); root.geometry('1440x960'); root.minsize(1080, 740)
    lab = AdcLab(root, a.version)
    if a.capture:
        lab.select(a.capture)

    def close():
        if lab.busy:
            messagebox.showinfo('FPGA running', 'Wait for the current run to finish before closing.'); return
        root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    root.mainloop()
