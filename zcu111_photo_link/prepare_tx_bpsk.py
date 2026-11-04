"""Photo -> 4-tone grey pixels -> canonical Huffman -> LDPC(384,194) -> real BPSK DAC waveforms (TDMS).

Default: images/wolfram.png at 20x20 with the Huffman header -> tx/bpsk_20x20/.
--no-header sends only Huffman data + CRC (table agreed in advance) -> tx/bpsk_20x20_nohdr/.
PC-side encoding only. No simulated channel noise is added and no RF hardware is controlled.

Every waveform is sized for the RF Data Converter Evaluation UI in BRAM mode:
  * DAC buffer limit 65,536 bytes -> at most 32,768 16-bit samples.
  * the UI only accepts lengths that are multiples of 32 samples.
  * FsDAC/FsADC = 6512.64/4096 = 159/100, so the repeat period must be a multiple of
    159 DAC samples to be a whole number of ADC samples. Lengths are therefore padded
    to multiples of lcm(159, 32) = 5088.
"""
from pathlib import Path
from collections import deque
import argparse, hashlib, json
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
from nptdms import TdmsWriter, TdmsFile, RootObject, GroupObject, ChannelObject
from codec import Codec, N, K
import huffman

FS_DAC, FS_ADC = 6512.64e6, 4096e6
DAC_LIMIT_SAMPLES = 65536 // 2
LENGTH_MULTIPLE = 5088  # lcm(159, 32)
PALETTE = np.array([0, 55, 165, 255])  # the four grey tones used in wolfram.png
PEAK = 8191


def repo_path(path):
    """Path relative to the repository when possible (keeps manifests machine-independent)."""
    p = Path(path).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.name


def downsample(path, size=20):
    """Pixel-art friendly resize: majority tone per cell, then small isolated
    black features (eyes, nose) keep one black pixel at their centroid."""
    a = np.asarray(Image.open(path).convert('L')).astype(int)
    idx = np.argmin(np.abs(a[..., None] - PALETTE), axis=2)
    ys, xs = np.nonzero(a < 240)
    x0, y0, x1, y1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
    side = max(x1 - x0, y1 - y0)
    ox, oy, cell = (x0 + x1 - side) / 2, (y0 + y1 - side) / 2, side / size
    ex = np.round(ox + np.arange(size + 1) * cell).astype(int)
    ey = np.round(oy + np.arange(size + 1) * cell).astype(int)
    level = np.zeros((size, size), int)
    for r in range(size):
        for c in range(size):
            sub = idx[max(ey[r], 0):ey[r + 1], max(ex[c], 0):ex[c + 1]].reshape(-1)
            level[r, c] = np.bincount(sub, minlength=4).argmax() if sub.size else 3
    step = 4
    black = idx[::step, ::step] == 0
    seen = np.zeros_like(black)
    h, w = black.shape
    for sy in range(h):
        for sx in range(w):
            if not black[sy, sx] or seen[sy, sx]:
                continue
            queue, pts = deque([(sy, sx)]), []
            seen[sy, sx] = True
            while queue:
                y, x = queue.popleft()
                pts.append((y, x))
                for v, u in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if 0 <= v < h and 0 <= u < w and black[v, u] and not seen[v, u]:
                        seen[v, u] = True
                        queue.append((v, u))
            if len(pts) * step * step < 3 * cell * cell:
                py, px = np.mean(pts, axis=0) * step
                r, c = int((py - oy) // cell), int((px - ox) // cell)
                if 0 <= r < size and 0 <= c < size:
                    level[r, c] = 0
    return PALETTE[level].astype(np.uint8)


def waveform(packet, sps, carrier_period):
    symbols = 1.0 - 2.0 * packet.astype(np.float64)
    n = np.arange(len(packet) * sps)
    wave = np.rint(PEAK * np.repeat(symbols, sps) * np.cos(2 * np.pi * (n % carrier_period) / carrier_period))
    # UI rejects lengths that are not multiples of 32 ("args size should be multiples of 32");
    # 159 keeps the repeat period integral at the ADC. lcm(159, 32) = 5088.
    wave = np.pad(wave, (0, (-len(wave)) % LENGTH_MULTIPLE))  # trailing zeros = short silent gap
    if len(wave) > DAC_LIMIT_SAMPLES:
        raise ValueError(f'{len(wave)} samples exceed the {DAC_LIMIT_SAMPLES}-sample BRAM DAC buffer')
    return wave


def write_tdms(path, wave, title):
    props = {'wf_start_offset': 0.0, 'wf_increment': 1 / FS_DAC, 'wf_samples': len(wave)}
    with TdmsWriter(path) as writer:
        writer.write_segment([
            RootObject(properties={'name': title, 'Version': 'V1.2.0', 'Channel': 'unknown',
                                   'Board': 'ZCU111', 'Package': 'G1517', 'Device': 'ZU28DR'}),
            GroupObject('sig'), ChannelObject('sig', 'I', wave, properties=props)])


def demodulate(path, symbols, sps, carrier_period):
    """Ideal coherent demodulation of the TDMS file as written on disk."""
    loaded = TdmsFile.read(path)['sig']['I'][:]
    n = np.arange(symbols * sps)
    metric = (loaded[:symbols * sps] * np.cos(2 * np.pi * (n % carrier_period) / carrier_period))
    return (metric.reshape(-1, sps).mean(axis=1) < 0).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--image', type=Path, default=ROOT / 'images' / 'wolfram.png')
    ap.add_argument('--size', type=int, default=20)
    ap.add_argument('--sps', type=int, default=16, help='DAC samples per BPSK symbol')
    ap.add_argument('--carrier-period', type=int, default=16, help='DAC samples per carrier cycle')
    ap.add_argument('--preamble', type=int, default=48, help='known sync symbols per packet')
    ap.add_argument('--no-header', action='store_true',
                    help='send only Huffman data + CRC; table and size agreed in advance')
    args = ap.parse_args()

    name = f'bpsk_{args.size}x{args.size}' + ('_nohdr' if args.no_header else '')
    out = ROOT / 'tx' / name
    out.mkdir(parents=True, exist_ok=True)
    codec = Codec()
    carrier = FS_DAC / args.carrier_period
    tag = f'{carrier / 1e6:.2f}MHz'.replace('.', 'p')
    prefix = f'photo{args.size}' + ('nh' if args.no_header else '')

    pixels = downsample(args.image, args.size)
    payload, hinfo = huffman.encode(pixels, header=not args.no_header)
    words = codec.encode(payload)
    preamble = np.random.default_rng(5203).integers(0, 2, args.preamble, dtype=np.uint8)

    Image.fromarray(pixels).save(out / f'source_{args.size}x{args.size}_gray.png')
    Image.fromarray(pixels).resize((400, 400), Image.Resampling.NEAREST).save(out / 'source_preview.png')

    # Option A: whole image in one repeated period. Option B: one codeword per period.
    plans = [('all', np.arange(len(words)))] + [(f'pkt{i + 1}', np.array([i])) for i in range(len(words))]
    files, recovered_words = [], {}
    for name, index in plans:
        packet = np.concatenate([preamble, words[index].reshape(-1)])
        wave = waveform(packet, args.sps, args.carrier_period)
        path = out / f'{prefix}_{name}_bpsk_{tag}.tdms'
        write_tdms(path, wave, f'LDPC photo {args.size}x{args.size} {name}')
        bits = demodulate(path, len(packet), args.sps, args.carrier_period)
        assert np.array_equal(bits, packet), f'{path.name}: demodulated bits differ'
        recovered_words[name] = bits[args.preamble:].reshape(-1, N)
        files.append(dict(file=path.name, codewords=[int(i) for i in index], symbols=len(packet),
                          dac_samples=len(wave), dac_bytes=2 * len(wave),
                          period_us=len(wave) / FS_DAC * 1e6,
                          adc_samples_per_period=len(wave) * 100 // 159,
                          sha256=hashlib.sha256(path.read_bytes()).hexdigest()))

    # Round trip: TDMS -> demod -> LDPC NMS (20 iterations) -> Huffman -> CRC -> pixels.
    checks = {}
    for label, rx in [('all', recovered_words['all']),
                      ('packets', np.concatenate([recovered_words[f'pkt{i + 1}'] for i in range(len(words))]))]:
        decoded = codec.reference(np.where(rx == 0, 15, -15).astype(np.float32), 20)
        restored, crc_ok = huffman.decode_payload(codec.payload(decoded, len(payload)), hinfo, pixels.shape)
        assert crc_ok and np.array_equal(restored, pixels), f'{label}: round trip failed'
        checks[label] = 'PASS'

    np.savez(out / 'reference.npz', pixels=pixels, payload_bits=payload, words=words, preamble=preamble)
    manifest = dict(
        source=repo_path(args.image), width=args.size, height=args.size, color='grayscale, 4 tones',
        resize='majority tone per cell + small black features kept at their centroid',
        palette=PALETTE.tolist(),
        huffman=hinfo, compression_ratio=round(hinfo['raw_bits'] / hinfo['total_bits'], 3),
        ldpc=dict(N=N, K=K, codewords=len(words), info_capacity_bits=len(words) * K,
                  zero_padding_bits=len(words) * K - len(payload), coded_bits=int(words.size),
                  parity_ok=codec.unsatisfied(words) == 0),
        modulation=dict(type='real BPSK, rectangular pulses', fs_dac_hz=FS_DAC, fs_adc_hz=FS_ADC,
                        carrier_hz=carrier, samples_per_symbol=args.sps, symbol_rate_hz=FS_DAC / args.sps,
                        preamble_symbols=args.preamble, preamble_seed=5203, digital_amplitude_peak=PEAK,
                        tdms_group='sig', tdms_channel='I', dac_buffer_limit_samples=DAC_LIMIT_SAMPLES),
        files=files, added_noise=False,
        offline_roundtrip=checks, hardware_roundtrip='NOT TESTED')
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
