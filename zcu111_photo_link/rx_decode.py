"""Decode ZCU111 ADC captures of the Huffman + LDPC photo waveforms (BPSK or QPSK).

  BPSK 20x20 : python rx_decode.py capture.tdms --tx tx/bpsk_20x20
  QPSK 30x30 : python rx_decode.py capture.tdms --tx tx/qpsk_30x30
  packet captures: give all packet captures in order (pkt1 pkt2 ...)

Steps per capture (PC only, offline):
  ADC I channel -> analytic band filter (one exact repeat period) -> mix to baseband
  -> preamble circular correlation (timing + carrier phase) -> per-symbol averaging
  -> complex soft symbols -> soft bits (BPSK: real part; QPSK: real and imaginary) -> LLR.
Then: hard bits -> Huffman ("without LDPC") and LLR -> NMS 20 iterations -> Huffman
-> CRC ("with LDPC"). The transmitted codewords in <tx>/reference.npz are used only
to count errors, never to help decoding (except the known preamble and, in
header-less mode, the agreed Huffman table).
"""
from pathlib import Path
from datetime import datetime
import argparse, json, sys
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
from nptdms import TdmsFile
from codec import Codec, N
import huffman, modem


def tx_dir(folder):
    """TX folder holding manifest.json + reference.npz (relative to the repo or absolute)."""
    p = Path(folder)
    return p if p.is_absolute() else ROOT / p


def kind_of(mod):
    return 'QPSK' if str(mod.get('type', '')).upper().startswith('QPSK') else 'BPSK'


def read_capture(path):
    tdms = TdmsFile.read(path)
    channel = None
    for group in tdms.groups():
        names = {c.name: c for c in group.channels()}
        if 'I' in names:
            channel = names['I']
            break
    if channel is None:
        raise ValueError(f'{path}: no channel named I')
    x = channel[:].astype(np.float64)
    fs = float(tdms.groups()[0].properties.get('Fs(MHz)', 0)) * 1e6 or 1 / channel.properties['wf_increment']
    return x, fs


def demodulate(x, fs, symbols, period, sps_dac, fs_dac, carrier, preamble_len, timing_steps=11):
    """Return phase-corrected complex soft symbols for one repeat period.

    `symbols` are the transmitted complex symbols; only the first `preamble_len`
    (the known preamble) are used, for timing and carrier phase.
    """
    if len(x) < period:
        raise ValueError(f'capture has {len(x)} samples; need at least one period = {period}')
    symbols = np.asarray(symbols, dtype=complex)
    rs = fs_dac / sps_dac                      # symbol rate
    T = fs / rs                                # ADC samples per symbol (non-integer)
    w = 2 * np.pi * carrier / fs
    seg = x[:period] - x[:period].mean()
    # Analytic band filter on exactly one period (signal is periodic in `period`).
    spec = np.fft.fft(seg)
    f = np.fft.fftfreq(period, 1 / fs)
    spec[(f <= 0) | (f > carrier + 1.5 * rs)] = 0
    a = np.fft.ifft(2 * spec)

    def baseband(n):                           # n may exceed period (periodic signal)
        return a[n % period] * np.exp(-1j * w * n)

    # Preamble template sampled at ADC times, delay 0.
    n0 = np.arange(period)
    sym = np.floor(n0 / T).astype(int)
    tmpl = np.zeros(period, dtype=complex)
    inside = sym < preamble_len
    tmpl[inside] = symbols[sym[inside]]
    # r(tau) = sum_n a[(n+tau)%P] * exp(-jw n) * conj(tmpl[n]); then remove exp(-jw tau).
    wv = np.exp(-1j * w * n0) * np.conj(tmpl)
    r = np.fft.ifft(np.fft.fft(a) * np.conj(np.fft.fft(np.conj(wv))))
    tau0 = int(np.argmax(np.abs(r)))
    phase = np.angle(r[tau0] * np.exp(-1j * w * tau0))

    def soft(tau):
        out = np.empty(len(symbols), dtype=complex)
        for i in range(len(symbols)):
            lo = int(np.ceil(tau + i * T + 1))
            hi = int(np.floor(tau + (i + 1) * T - 1))
            n = np.arange(lo, hi + 1)
            out[i] = np.mean(baseband(n)) * np.exp(-1j * phase)
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


def load_tx(tx):
    manifest = json.loads((tx / 'manifest.json').read_text(encoding='utf-8'))
    ref = np.load(tx / 'reference.npz')
    return manifest, ref


def receive(captures, tx):
    """Demodulate captures against the waveform described in `tx`.
    Returns (llr per codeword bit [n_words, N], snr_db, per-capture info)."""
    manifest, ref = load_tx(tx)
    words, preamble = ref['words'], ref['preamble']
    mod = manifest['modulation']
    kind = kind_of(mod)
    files = {f['file'].split('_')[1]: f for f in manifest['files']}
    if len(captures) == 1:
        plans = [files['all']]
    else:
        plans = [files[k] for k in sorted((k for k in files if k.startswith('pkt')), key=lambda k: int(k[3:]))]
        if len(plans) != len(captures):
            raise ValueError(f'give 1 capture (all) or {len(plans)} packet captures in order')
    soft, per_capture = [], []
    for path, entry in zip(captures, plans):
        index = np.array(entry.get('codewords', []), dtype=int)
        x, fs = read_capture(path)
        if abs(fs - mod['fs_adc_hz']) > 1e3:
            raise ValueError(f'{path}: Fs {fs / 1e6} MHz, expected {mod["fs_adc_hz"] / 1e6} MHz')
        if (entry['dac_samples'] * 100) % 159:
            raise ValueError('DAC period is not an integer number of ADC samples')
        period = entry['dac_samples'] * 100 // 159
        symbols = modem.packet_symbols(preamble, words[index].reshape(-1), kind)
        y, info = demodulate(x, fs, symbols, period, mod['samples_per_symbol'], mod['fs_dac_hz'],
                             mod['carrier_hz'], len(preamble))
        pre_err = int(np.count_nonzero(modem.preamble_decisions(y[:len(preamble)], kind) != preamble))
        soft.append(modem.soft_bits(y[len(preamble):], kind).reshape(-1, N))
        per_capture.append(dict(file=str(path), plan=entry['file'], modulation=kind, adc_samples=len(x),
                                period_adc_samples=period, peak_abs_adc=float(np.max(np.abs(x))),
                                preamble_bit_errors=pre_err, **info))
    llr, snr_db = to_llr(np.concatenate(soft))
    return llr, snr_db, per_capture


def panel(images, labels, scale=10):
    side = images[0].shape[0] * scale
    canvas = Image.new('L', (len(images) * (side + 20) + 20, side + 60), 255)
    draw = ImageDraw.Draw(canvas)
    for i, (im, label) in enumerate(zip(images, labels)):
        x = 20 + i * (side + 20)
        canvas.paste(Image.fromarray(im).resize((side, side), Image.Resampling.NEAREST), (x, 40))
        draw.text((x, 12), label, fill=0)
    return canvas


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('captures', nargs='+', type=Path)
    ap.add_argument('--iterations', type=int, default=20)
    ap.add_argument('--out', type=Path, default=None)
    ap.add_argument('--tx', required=True, help='TX folder of the transmitted waveform, e.g. tx/qpsk_30x30')
    args = ap.parse_args()

    tx = tx_dir(args.tx)
    manifest, ref = load_tx(tx)
    hinfo = manifest['huffman']
    words, payload, pixels = ref['words'], ref['payload_bits'], ref['pixels']
    llr, snr_db, per_capture = receive(args.captures, tx)

    codec = Codec()
    hard = (llr < 0).astype(np.uint8)
    raw_errors = int(np.count_nonzero(hard != words))
    # Without LDPC: take the information positions of the hard decisions directly.
    raw_payload = codec.payload(hard, len(payload))
    decoded = codec.reference(llr, args.iterations)
    dec_payload = codec.payload(decoded, len(payload))
    if hinfo.get('header_sent', True):
        raw_img, raw_count, raw_note = huffman.decode_partial(raw_payload, pixels.shape)
        try:
            dec_img, crc_ok = huffman.decode(dec_payload)
            dec_note = 'CRC OK' if crc_ok else 'CRC FAILED'
        except ValueError as error:
            dec_img, _, dec_note = huffman.decode_partial(dec_payload, pixels.shape)
            crc_ok, dec_note = False, f'Huffman stream broken: {error}'
    else:
        raw_img, raw_count, raw_crc = huffman.decode_known_table(raw_payload, hinfo, pixels.shape)
        raw_note = f'{raw_count}/{pixels.size} pixels decoded (table known), CRC ' + ('OK' if raw_crc else 'FAILED')
        dec_img, crc_ok = huffman.decode_payload(dec_payload, hinfo, pixels.shape)
        dec_note = 'CRC OK' if crc_ok else 'CRC FAILED'

    out = args.out or ROOT / 'rx_results' / datetime.now().strftime('rx_%Y%m%d_%H%M%S')
    out.mkdir(parents=True, exist_ok=True)
    result = dict(
        # BPSK: per-symbol SNR. QPSK: per I/Q component (each carries one bit).
        captures=per_capture, estimated_symbol_snr_db=snr_db,
        channel_bit_errors=raw_errors, channel_ber=raw_errors / words.size, coded_bits=int(words.size),
        payload_bit_errors_without_ldpc=int(np.count_nonzero(raw_payload != payload)),
        without_ldpc=dict(huffman=raw_note, pixel_errors=int(np.count_nonzero(raw_img != pixels))),
        payload_bit_errors_with_ldpc=int(np.count_nonzero(dec_payload != payload)),
        unsatisfied_codewords_after_ldpc=codec.unsatisfied(decoded),
        with_ldpc=dict(huffman=dec_note, crc_ok=bool(crc_ok),
                       pixel_errors=int(np.count_nonzero(dec_img != pixels)),
                       exact_image=bool(np.array_equal(dec_img, pixels))),
        iterations_limit=args.iterations, tx_folder=tx.name, huffman_header_sent=hinfo.get('header_sent', True),
        note=f'Errors are counted against {tx.name}/reference.npz; decoding uses only the received signal, '
             'the known preamble and (header-less mode) the agreed Huffman table.')
    (out / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    llr.astype('<f4').tofile(out / 'llr.f32')
    big = pixels.shape[0] * 8
    Image.fromarray(raw_img).resize((big, big), Image.Resampling.NEAREST).save(out / 'received_no_ldpc.png')
    Image.fromarray(dec_img).resize((big, big), Image.Resampling.NEAREST).save(out / 'decoded_ldpc.png')
    panel([pixels, raw_img, dec_img],
          ['Transmitted', f'Received, no LDPC ({raw_errors} ch. bit err)', f'After LDPC ({dec_note})']
          ).save(out / 'comparison.png')
    print(json.dumps(result, indent=2))
    print('Saved to', out)


if __name__ == '__main__':
    main()
