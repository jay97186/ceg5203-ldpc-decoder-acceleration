"""Validate hashes, byte layouts, encoder parity, and stored reference metrics."""
from pathlib import Path
import argparse
import hashlib
import json
import numpy as np
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    root = args.root
    meta = json.loads((root/'manifest.json').read_text())
    for name, item in meta['files'].items():
        raw = (root/name).read_bytes()
        assert len(raw) == item['bytes'], name
        assert hashlib.sha256(raw).hexdigest() == item['sha256'], name
        if 'shape' in item:
            assert np.prod(item['shape'])*np.dtype(item['dtype']).itemsize == len(raw), name

    def read(name):
        item = meta['files'][name]
        return np.fromfile(root/name, dtype=item['dtype']).reshape(item['shape'])

    checks = read('code/checks.i32')
    info = read('code/info.i32')
    edges = read('code/variable_edges.i32')
    assert np.array_equal(checks.reshape(-1)[edges], np.broadcast_to(np.arange(meta['n'])[:,None], edges.shape))
    for case in meta['cases']:
        im = Image.open(root/case['image'])
        assert im.mode == 'RGB' and im.size == (256,192)
        bits = np.unpackbits(np.asarray(im).reshape(-1))
        tx, llr, ref = read(case['tx']), read(case['llr']), read(case['reference'])
        assert tx.shape == llr.shape == ref.shape == (case['frames'],meta['n'])
        assert np.all((tx == 0) | (tx == 1)) and np.all((ref == 0) | (ref == 1))
        assert np.isfinite(llr).all() and np.max(np.abs(llr)) <= 30
        assert not np.bitwise_xor.reduce(tx[:,checks], axis=2).any()
        assert np.array_equal(tx[:,info].reshape(-1)[:len(bits)],bits)
        assert not tx[:,info].reshape(-1)[len(bits):].any()
        payload = ref[:,info].reshape(-1)[:len(bits)]
        assert np.count_nonzero(payload != bits) == case['reference_payload_errors']
        assert np.count_nonzero(ref != tx) == case['reference_codeword_errors']
        assert np.count_nonzero(np.bitwise_xor.reduce(ref[:,checks],axis=2).any(axis=1)) == case['reference_unsatisfied_frames']
        assert np.count_nonzero((llr < 0) != tx) == case['input_hard_bit_errors']
        decoded = np.asarray(Image.open(root/Path(case['reference']).parent/'decoded.png'))
        assert np.array_equal(decoded, np.packbits(payload).reshape(192,256,3))
        if case['channel']['channel'] == 'none':
            assert np.array_equal(ref,tx)
    print(f'PASS: {len(meta["files"])} file hashes/layouts; {len(meta["cases"])} cases; image reconstruction, adjacency, parity and recorded metrics.')


if __name__ == '__main__':
    main()
