"""Show how LDPC correction progresses with the NMS iteration limit for one real
ADC capture (or the packet captures in order).

  python rx_iterations.py capture.tdms --tx tx/qpsk_30x30 [--show 0 1 2 5 10 20] [--out DIR]

Outputs (default rx_results/<capture>_iterations*/):
  iterations.png   one decoded image per iteration limit, with remaining errors
  iterations.csv   iteration, codeword bit errors, payload bit errors, unsatisfied codewords, CRC
Errors are counted against <tx>/reference.npz (what was sent); decoding uses only the
received signal, the known preamble and, for header-less waveforms, the agreed Huffman table.
"""
from pathlib import Path
import argparse, csv
import numpy as np
from PIL import Image, ImageDraw

import rx_decode as rx
from codec import Codec
import huffman


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('captures', nargs='+', type=Path)
    ap.add_argument('--tx', required=True, help='TX folder of the transmitted waveform, e.g. tx/qpsk_30x30')
    ap.add_argument('--show', type=int, nargs='+', default=[0, 1, 2, 3, 5, 10, 20])
    ap.add_argument('--max', type=int, default=20)
    ap.add_argument('--known-table', action='store_true',
                    help='receiver knows the Huffman table and size in advance; ignore the sent header')
    ap.add_argument('--out', type=Path, default=None)
    args = ap.parse_args()

    tx = rx.tx_dir(args.tx)
    manifest, ref = rx.load_tx(tx)
    header_sent = manifest['huffman'].get('header_sent', True)
    if not header_sent:
        args.known_table = True  # nothing else to decode with
    words, payload, pixels = ref['words'], ref['payload_bits'], ref['pixels']
    llr, snr_db, _ = rx.receive(args.captures, tx)

    codec = Codec()
    rows, images = [], {}
    for it in range(0, max(args.max, max(args.show)) + 1):
        dec = codec.reference(llr, it)
        bits = codec.payload(dec, len(payload))
        if args.known_table:
            img, _, crc_ok = huffman.decode_known_table(bits, manifest['huffman'], pixels.shape)
        else:
            try:
                img, crc_ok = huffman.decode(bits)
            except ValueError:
                img, _, _ = huffman.decode_partial(bits, pixels.shape)
                crc_ok = False
        rows.append(dict(iteration=it, codeword_bit_errors=int(np.count_nonzero(dec != words)),
                         payload_bit_errors=int(np.count_nonzero(bits != payload)),
                         unsatisfied_codewords=codec.unsatisfied(dec), crc_ok=bool(crc_ok),
                         pixel_errors=int(np.count_nonzero(img != pixels))))
        images[it] = img

    suffix = ('_iterations_no_header' if not header_sent else
              '_iterations_known_table' if args.known_table else '_iterations')
    out = args.out or rx.ROOT / 'rx_results' / f'{args.captures[0].stem}{suffix}'
    out.mkdir(parents=True, exist_ok=True)
    with open(out / 'iterations.csv', 'w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    scale, gap = 8, 16
    side = pixels.shape[0] * scale
    width = gap + (len(args.show) + 1) * (side + gap)
    canvas = Image.new('L', (width, side + 96), 255)
    draw = ImageDraw.Draw(canvas)
    draw.text((gap, 6), f'{args.captures[0].name}   estimated symbol SNR {snr_db:.1f} dB   '
                        f'channel bit errors {rows[0]["codeword_bit_errors"]}/{words.size}'
                        + f'   {rx.kind_of(manifest["modulation"])}'
                        + ('   no header sent, table agreed in advance' if not header_sent else
                           '   Huffman table known at receiver' if args.known_table else ''), fill=0)
    panels = [('Transmitted', pixels, '')] + [
        (f'Iteration {it}', images[it],
         f'{rows[it]["codeword_bit_errors"]} bit err\n' + ('CRC OK' if rows[it]['crc_ok'] else 'CRC fail'))
        for it in args.show]
    for i, (title, img, note) in enumerate(panels):
        x = gap + i * (side + gap)
        draw.text((x, 26), title, fill=0)
        canvas.paste(Image.fromarray(img).resize((side, side), Image.Resampling.NEAREST), (x, 44))
        draw.multiline_text((x, 48 + side), note, fill=0)
    canvas.save(out / 'iterations.png')
    for r in rows:
        print(r)
    print('Saved to', out)


if __name__ == '__main__':
    main()
