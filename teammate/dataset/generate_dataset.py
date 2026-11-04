"""Build fixed procedural images and decoder vectors using ../ldpc.py.

No GUI/camera/PyTorch. Existing manifest prevents accidental overwrite.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import platform
import numpy as np
import PIL
from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / 'ldpc.py'
spec = importlib.util.spec_from_file_location('ldpc_reference', SOURCE)
ldpc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ldpc)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_image(index):
    # Reuse original pixels; do not regenerate text with a different font.
    path = ROOT.parent / 'dataset' / 'images' / f'image_{index+1:02d}.png'
    with Image.open(path) as source:
        assert source.mode == 'RGB' and source.size == (256, 192)
        return source.copy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT)
    args = parser.parse_args()
    out = args.output.resolve()
    if (out/'manifest.json').exists():
        parser.error('Dataset already exists. Use --output with a new directory.')
    out.mkdir(parents=True, exist_ok=True)
    ldpc.self_test()
    manifest = dict(format_version=1, description='10 original synthetic RGB images, 10 fixed AWGN 3 dB decoder cases',
                    width=256, height=192, channels=3, matrix_seed=5203,
                    z=64, alpha=0.75, clip=30.0, iterations=20,
                    reference_batch_size=256, schedule='flooding',
                    iteration_policy='20 calls; freeze words/q if syndrome zero at start of step; no batch early exit',
                    python=platform.python_version(), numpy=np.__version__, pillow=PIL.__version__,
                    reference_source_sha256=digest(SOURCE), files={}, cases=[])

    def save_array(rel, array, dtype):
        path = out/rel
        path.parent.mkdir(parents=True, exist_ok=True)
        arr = np.ascontiguousarray(array, dtype=dtype)
        arr.tofile(path)
        manifest['files'][rel] = dict(dtype=arr.dtype.str, shape=list(arr.shape),
                                    order='C', bytes=path.stat().st_size, sha256=digest(path))

    def save_image(rel, im):
        path = out/rel
        path.parent.mkdir(parents=True, exist_ok=True)
        im.save(path)
        manifest['files'][rel] = dict(format='PNG', bytes=path.stat().st_size, sha256=digest(path))

    code = ldpc.make_code(64, 5203)
    n, m, k = code['H'].shape[1], code['H'].shape[0], len(code['info'])
    manifest.update(n=n, m=m, k=k, edges=int(code['checks'].size))
    for key in ('checks', 'variables', 'variable_edges', 'info', 'pivots', 'shifts'):
        save_array(f'code/{key}.i32', code[key], '<i4')
    for key in ('H', 'parity_map'):
        save_array(f'code/{key}.u8', code[key], 'u1')
    sheet = Image.new('RGB', (5*256, 2*216), '#eeeeee')
    for i in range(10):
        name = f'image_{i+1:02d}'
        im = make_image(i)
        save_image(f'images/{name}.png', im)
        sheet.paste(im, ((i % 5)*256, (i//5)*216))
        ImageDraw.Draw(sheet).text(((i % 5)*256+8, (i//5)*216+194), name, fill='black', font=ldpc.font(16))
        bits = np.unpackbits(np.asarray(im).reshape(-1))
        sent = ldpc.encode(bits, code)
        assert not ldpc.syndrome(sent, code['checks']).any()
        assert np.array_equal(sent[:, code['info']].reshape(-1)[:bits.size], bits)
        save_array(f'images/{name}_tx.u8', sent, 'u1')
        configs = [('awgn', 3.0, 2026+i)]
        for channel, db, seed in configs:
            case_id = f'{name}_{channel}' + (f'_{int(db)}db' if channel == 'awgn' else '')
            prefix = f'cases/{case_id}'
            rx, config, llr = ldpc.apply_channel(sent, channel=channel, p=0.01,
                ebn0_db=db, rate=k/n, seed=seed, return_llr=True)
            save_array(f'{prefix}/llr.f32', llr, '<f4')
            words_out = np.empty_like(sent)
            for start in range(0, len(sent), 256):
                x = llr[start:start+256]
                words = (x < 0).astype(np.uint8)
                q = x[:, code['checks']].copy()
                for iteration in range(20):
                    words, q = ldpc.nms_step(x, q, words, code, .75, 30.)
                    if start == 0 and iteration == 0:
                        save_array(f'{prefix}/step1_words.u8', words, 'u1')
                        save_array(f'{prefix}/step1_q.f32', q, '<f4')
                words_out[start:start+len(x)] = words
            save_array(f'{prefix}/reference_words.u8', words_out, 'u1')
            payload = words_out[:, code['info']].reshape(-1)[:bits.size]
            errors = int(np.count_nonzero(payload != bits))
            if channel == 'none':
                assert np.array_equal(words_out, sent)
            save_image(f'{prefix}/decoded.png', Image.fromarray(np.packbits(payload).reshape(192,256,3)))
            hard = (llr < 0).astype(np.uint8)[:, code['info']].reshape(-1)[:bits.size]
            save_image(f'{prefix}/received.png', Image.fromarray(np.packbits(hard).reshape(192,256,3)))
            case = dict(id=case_id, image=f'images/{name}.png', tx=f'images/{name}_tx.u8',
                        llr=f'{prefix}/llr.f32', reference=f'{prefix}/reference_words.u8',
                        frames=len(sent), payload_bits=int(bits.size), padding_bits=int(len(sent)*k-bits.size),
                        channel=config, noise_seed=seed,
                        input_hard_bit_errors=int(np.count_nonzero((llr < 0) != sent)),
                        input_payload_errors=int(np.count_nonzero(hard != bits)),
                        reference_payload_errors=errors, reference_payload_ber=errors/int(bits.size),
                        reference_codeword_errors=int(np.count_nonzero(words_out != sent)),
                        reference_unsatisfied_frames=int(np.count_nonzero(ldpc.syndrome(words_out,code['checks']).any(axis=1))))
            manifest['cases'].append(case)
            print(f'{case_id}: frames={len(sent)}, payload errors={errors}', flush=True)
    save_image('preview.png', sheet)
    manifest['total_binary_and_png_bytes'] = sum(v['bytes'] for v in manifest['files'].values())
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    print(f'Saved {len(manifest["cases"])} cases to {out}', flush=True)


if __name__ == '__main__':
    main()
