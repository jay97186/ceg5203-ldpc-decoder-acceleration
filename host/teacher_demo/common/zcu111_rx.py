"""ZCU111 ADC capture -> soft bits -> LLR for the Kria FPGA decoder.

Same receiver as the zcu111_photo_link project: analytic band filter over one
exact repeat period, preamble circular correlation (timing + carrier phase),
per-symbol averaging, BPSK/QPSK soft bits, LLR clipped to +-30.
The transmitted reference (zcu111_tx/<waveform>/reference.npz) is used only to
count errors, never to help decoding (except the known 48-symbol preamble and,
for the header-less QPSK format, the agreed Huffman table).
"""
from pathlib import Path
import json, sys
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'deps'))
from nptdms import TdmsFile
from codec import Codec, N
import huffman, modem

TX_ROOT = ROOT.parent / 'zcu111_tx'
CODEC = Codec()
WAVEFORMS = {'QPSK 30x30': 'qpsk_30x30', 'BPSK 20x20': 'bpsk_20x20'}


def guess_waveform(path):
    name = Path(path).name.lower()
    return 'BPSK 20x20' if ('bpsk' in name or 'rx_all' in name) else 'QPSK 30x30'


def kind_of(mod):
    return 'QPSK' if str(mod.get('type', '')).upper().startswith('QPSK') else 'BPSK'


def load_tx(waveform):
    folder = TX_ROOT / WAVEFORMS[waveform]
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    ref = np.load(folder / 'reference.npz')
    return folder, manifest, {k: ref[k] for k in ref.files}


def read_capture(path):
    tdms = TdmsFile.read(path)
    channel = None
    for group in tdms.groups():
        names = {c.name: c for c in group.channels()}
        if 'I' in names:
            channel = names['I']
            break
    if channel is None:
        raise ValueError(f'{path}: no ADC channel named I')
    x = channel[:].astype(np.float64)
    fs = float(tdms.groups()[0].properties.get('Fs(MHz)', 0)) * 1e6 or 1 / channel.properties['wf_increment']
    return x, fs


def demodulate(x, fs, symbols, period, sps_dac, fs_dac, carrier, preamble_len, timing_steps=11):
    if len(x) < period:
        raise ValueError(f'Capture has {len(x)} samples; at least one period ({period}) is needed. '
                         'Set ADC Samples to 16384.')
    symbols = np.asarray(symbols, dtype=complex)
    rs = fs_dac / sps_dac
    T = fs / rs
    w = 2 * np.pi * carrier / fs
    seg = x[:period] - x[:period].mean()
    spec = np.fft.fft(seg)
    f = np.fft.fftfreq(period, 1 / fs)
    spec[(f <= 0) | (f > carrier + 1.5 * rs)] = 0
    a = np.fft.ifft(2 * spec)
    n0 = np.arange(period)
    sym = np.floor(n0 / T).astype(int)
    tmpl = np.zeros(period, dtype=complex)
    inside = sym < preamble_len
    tmpl[inside] = symbols[sym[inside]]
    wv = np.exp(-1j * w * n0) * np.conj(tmpl)
    r = np.fft.ifft(np.fft.fft(a) * np.conj(np.fft.fft(np.conj(wv))))
    tau0 = int(np.argmax(np.abs(r)))
    phase = np.angle(r[tau0] * np.exp(-1j * w * tau0))

    def soft(tau):
        out = np.empty(len(symbols), dtype=complex)
        for i in range(len(symbols)):
            n = np.arange(int(np.ceil(tau + i * T + 1)), int(np.floor(tau + (i + 1) * T - 1)) + 1)
            out[i] = np.mean(a[n % period] * np.exp(-1j * w * n)) * np.exp(-1j * phase)
        return out

    known = symbols[:preamble_len]
    best = max((float(np.real(np.vdot(known, soft(tau0 + d)[:preamble_len]))), tau0 + d)
               for d in np.linspace(-0.5, 0.5, timing_steps))
    y = soft(best[1])
    corr = best[0] / (np.sum(np.abs(known)) * np.mean(np.abs(y)) + 1e-12)
    return y, dict(timing_adc_samples=float(best[1]), carrier_phase_rad=float(phase),
                   preamble_correlation=float(corr))


def to_llr(y):
    mu = np.mean(np.abs(y))
    var = np.mean((np.abs(y) - mu) ** 2) + 1e-12
    return np.clip(2 * mu * y / var, -30, 30).astype(np.float32), float(10 * np.log10(mu * mu / var))


def decode_image(words, manifest, ref):
    """Codewords -> (pixels, crc_ok, note). Never raises on corrupted streams."""
    bits = CODEC.payload(words, len(ref['payload_bits']))
    hinfo, shape = manifest['huffman'], ref['pixels'].shape
    if hinfo.get('header_sent', True):
        try:
            img, ok = huffman.decode(bits)
            return img, bool(ok), 'CRC OK' if ok else 'CRC failed'
        except ValueError:
            img, _, note = huffman.decode_partial(bits, shape)
            return img, False, 'Header corrupted'
    img, count, ok = huffman.decode_known_table(bits, hinfo, shape)
    return img, bool(ok and count == ref['pixels'].size), 'CRC OK' if ok else 'CRC failed'


def receive(capture, waveform):
    """Return dict with llr [n_codewords, 384] float32 and receiver statistics."""
    folder, manifest, ref = load_tx(waveform)
    mod = manifest['modulation']
    kind = kind_of(mod)
    entry = next(f for f in manifest['files'] if f['file'].split('_')[1] == 'all')
    x, fs = read_capture(capture)
    if abs(fs - mod['fs_adc_hz']) > 1e3:
        raise ValueError(f'ADC Fs is {fs / 1e6:.3f} MHz, expected {mod["fs_adc_hz"] / 1e6:.3f} MHz')
    period = entry['dac_samples'] * 100 // 159
    words, preamble = ref['words'], ref['preamble']
    symbols = modem.packet_symbols(preamble, words.reshape(-1), kind)
    y, info = demodulate(x, fs, symbols, period, mod['samples_per_symbol'], mod['fs_dac_hz'],
                         mod['carrier_hz'], len(preamble))
    pre_err = int(np.count_nonzero(modem.preamble_decisions(y[:len(preamble)], kind) != preamble))
    llr, snr = to_llr(modem.soft_bits(y[len(preamble):], kind).reshape(-1, N))
    hard = (llr < 0).astype(np.uint8)
    return dict(llr=llr, hard=hard, snr_db=snr, kind=kind, waveform=waveform, tx_folder=str(folder),
                manifest=manifest, ref=ref, adc_samples=len(x), peak_abs_adc=float(np.max(np.abs(x))),
                preamble_bit_errors=pre_err, channel_bit_errors=int(np.count_nonzero(hard != words)), **info)
