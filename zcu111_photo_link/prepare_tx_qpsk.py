"""Photo -> 4-tone grey pixels -> header-less Huffman + CRC -> LDPC(384,194) -> QPSK -> DAC TDMS.

Default: images/wolfram.png at 30x30 -> tx/qpsk_30x30/. PC-side encoding only;
no simulated noise is added, no RF hardware is controlled.

Same RF settings as the BPSK version: Fs 6512.64 MSPS, 16 samples/symbol,
carrier 407.04 MHz, 48-symbol preamble, lengths multiple of 5088 = lcm(159, 32),
whole image in one waveform <= 32,768 DAC samples (BRAM) -> 16,000 ADC samples per period.
QPSK carries 2 bits per symbol, so 8 codewords fit instead of 4.
"""
from pathlib import Path
import argparse, hashlib, json
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
from nptdms import TdmsFile
from codec import Codec, N, K
import huffman, modem
from prepare_tx_bpsk import (downsample, write_tdms, repo_path, PALETTE, PEAK, FS_DAC, FS_ADC,
                             DAC_LIMIT_SAMPLES, LENGTH_MULTIPLE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--image', type=Path, default=ROOT / 'images' / 'wolfram.png')
    ap.add_argument('--size', type=int, default=30)
    ap.add_argument('--sps', type=int, default=16)
    ap.add_argument('--carrier-period', type=int, default=16)
    ap.add_argument('--preamble', type=int, default=48)
    ap.add_argument('--packets', type=int, default=4, help='also split into this many waveforms')
    args = ap.parse_args()
    kind = 'QPSK'

    out = ROOT / 'tx' / f'qpsk_{args.size}x{args.size}'
    out.mkdir(parents=True, exist_ok=True)
    codec = Codec()
    carrier = FS_DAC / args.carrier_period
    tag = f'{carrier / 1e6:.2f}MHz'.replace('.', 'p')
    prefix = f'photo{args.size}q'

    pixels = downsample(args.image, args.size)
    payload, hinfo = huffman.encode(pixels, header=False)
    words = codec.encode(payload)
    preamble = np.random.default_rng(5203).integers(0, 2, args.preamble, dtype=np.uint8)
    Image.fromarray(pixels).save(out / f'source_{args.size}x{args.size}_gray.png')
    Image.fromarray(pixels).resize((args.size * 15, args.size * 15), Image.Resampling.NEAREST).save(out / 'source_preview.png')

    groups = np.array_split(np.arange(len(words)), args.packets)
    plans = [('all', np.arange(len(words)))] + [(f'pkt{i + 1}', g) for i, g in enumerate(groups)]
    files, rx = [], {}
    for name, index in plans:
        symbols = modem.packet_symbols(preamble, words[index].reshape(-1), kind)
        wave = modem.passband(symbols, args.sps, args.carrier_period, PEAK)
        wave = np.pad(wave, (0, (-len(wave)) % LENGTH_MULTIPLE))
        if len(wave) > DAC_LIMIT_SAMPLES:
            raise ValueError(f'{name}: {len(wave)} samples exceed the {DAC_LIMIT_SAMPLES}-sample BRAM buffer')
        path = out / f'{prefix}_{name}_qpsk_{tag}.tdms'
        write_tdms(path, wave, f'LDPC photo {args.size}x{args.size} QPSK {name}')
        loaded = TdmsFile.read(path)['sig']['I'][:]
        y = modem.ideal_demod(loaded, len(symbols), args.sps, args.carrier_period) / PEAK
        pre = modem.preamble_decisions(y[:args.preamble], kind)
        bits = (modem.soft_bits(y[args.preamble:], kind) < 0).astype(np.uint8)
        assert np.array_equal(pre, preamble) and np.array_equal(bits, words[index].reshape(-1)), f'{name}: demod mismatch'
        rx[name] = bits.reshape(-1, N)
        files.append(dict(file=path.name, codewords=[int(i) for i in index], symbols=len(symbols),
                          dac_samples=len(wave), dac_bytes=2 * len(wave), period_us=len(wave) / FS_DAC * 1e6,
                          adc_samples_per_period=len(wave) * 100 // 159,
                          sha256=hashlib.sha256(path.read_bytes()).hexdigest()))

    checks = {}
    for label, w in [('all', rx['all']), ('packets', np.concatenate([rx[f'pkt{i + 1}'] for i in range(len(groups))]))]:
        dec = codec.reference(np.where(w == 0, 15, -15).astype(np.float32), 20)
        img, ok = huffman.decode_payload(codec.payload(dec, len(payload)), hinfo, pixels.shape)
        assert ok and np.array_equal(img, pixels), f'{label}: round trip failed'
        checks[label] = 'PASS'

    np.savez(out / 'reference.npz', pixels=pixels, payload_bits=payload, words=words, preamble=preamble)
    manifest = dict(
        source=repo_path(args.image), width=args.size, height=args.size, color='grayscale, 4 tones',
        resize='majority tone per cell + small black features kept at their centroid', palette=PALETTE.tolist(),
        huffman=hinfo, compression_ratio=round(hinfo['raw_bits'] / hinfo['total_bits'], 3),
        ldpc=dict(N=N, K=K, codewords=len(words), info_capacity_bits=len(words) * K,
                  zero_padding_bits=len(words) * K - len(payload), coded_bits=int(words.size),
                  parity_ok=codec.unsatisfied(words) == 0),
        modulation=dict(type=kind, bits_per_symbol=2, mapping='Gray: b0 -> I, b1 -> Q, (1-2b)/sqrt2',
                        preamble_mapping='(1-2p)(1+j)/sqrt2', fs_dac_hz=FS_DAC, fs_adc_hz=FS_ADC,
                        carrier_hz=carrier, samples_per_symbol=args.sps, symbol_rate_hz=FS_DAC / args.sps,
                        preamble_symbols=args.preamble, preamble_seed=5203, digital_amplitude_peak=PEAK,
                        tdms_group='sig', tdms_channel='I', dac_buffer_limit_samples=DAC_LIMIT_SAMPLES),
        files=files, added_noise=False, offline_roundtrip=checks, hardware_roundtrip='NOT TESTED')
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
