"""Regenerate fixed tables and self-contained C++ test vectors from Python NMS."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import numpy as np


def float_literal(x):
    text = format(float(np.float32(x)), '.9g')
    if '.' not in text and 'e' not in text.lower(): text += '.0'
    return text + 'f'


def array_rows(a, formatter=str):
    return ',\n'.join('    {' + ', '.join(formatter(x) for x in row) + '}' for row in a)


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, default=Path('C:/Users/jay/Documents/Codex/2026-10-17/https-nus-ceg5203-github-io-project/outputs/for_xiong/ldpc/ldpc.py'))
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('python_nms_reference', args.reference)
    ref = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ref)  # Import does not trigger the interactive main().
    code = ref.make_code(z=64, seed=5203)
    assert code['checks'].shape == (192, 6)
    assert code['variable_edges'].shape == (384, 3)
    assert len(code['info']) == 194
    tables = '#ifndef NMS_TABLES_H\n#define NMS_TABLES_H\n#include "nms_decoder.h"\n'
    tables += '// Generated from the existing Python matrix; seed 5203, Z=64.\n'
    tables += 'static const unsigned short NMS_CHECKS[NMS_M][NMS_DC] = {\n'+array_rows(code['checks'])+'\n};\n'
    tables += 'static const unsigned short NMS_VARIABLE_EDGES[NMS_N][NMS_DV] = {\n'+array_rows(code['variable_edges'])+'\n};\n#endif\n'
    (root/'nms_tables.h').write_text(tables, encoding='utf-8')

    rng = np.random.default_rng(5203)
    data = rng.integers(0, 2, (8*194), dtype=np.uint8)
    sent = ref.encode(data, code)
    assert not ref.syndrome(sent, code['checks']).any()
    inputs = []
    for index in range(2):
        inputs.append((f'clean_{index}', (1-2*sent[index].astype(np.float32))*3))
    for bit in [0, 383]:
        damaged = sent[0].copy()
        damaged[bit] ^= 1
        inputs.append((f'single_error_{bit}', (1-2*damaged.astype(np.float32))*3))
    for p in [.01, .05, .1]:
        _, _, llr = ref.apply_channel(sent, channel='bsc', p=p, ebn0_db=6,
                                     rate=194/384, seed=2026, return_llr=True)
        for index in range(4): inputs.append((f'bsc_{p}_{index}', llr[index]))
    for db in [2., 6.]:
        _, _, llr = ref.apply_channel(sent, channel='awgn', p=.01, ebn0_db=db,
                                     rate=194/384, seed=2026, return_llr=True)
        for index in range(4): inputs.append((f'awgn_{db}_{index}', llr[index]))
    inputs.append(('zero_llr', np.zeros(384, dtype=np.float32)))

    cases = []
    for name, values in inputs:
        for limit in [0, 1, 2, 5, 20]:
            llr = np.clip(values, -30, 30).astype(np.float32)[None, :]
            words = (llr < 0).astype(np.uint8)
            q = llr[:, code['checks']].copy()
            used = 0
            for _ in range(limit):
                if not ref.syndrome(words, code['checks']).any(): break
                words, q = ref.nms_step(llr, q, words, code, alpha=.75)
                used += 1
            cases.append((f'{name}_limit{limit}', llr[0], words[0], limit, used))

    header = '#ifndef NMS_VECTORS_H\n#define NMS_VECTORS_H\n#include "nms_decoder.h"\n'
    header += '// Testbench only. These arrays are NOT part of the hardware design.\n'
    header += f'static const int NMS_NUM_TESTS = {len(cases)};\n'
    header += 'static const char * const NMS_TEST_NAMES[NMS_NUM_TESTS] = {\n'
    header += ',\n'.join('    '+json.dumps(c[0]) for c in cases)+'\n};\n'
    header += 'static const float NMS_TEST_LLR[NMS_NUM_TESTS][NMS_N] = {\n'
    header += array_rows([c[1] for c in cases], float_literal)+'\n};\n'
    header += 'static const unsigned char NMS_TEST_EXPECTED[NMS_NUM_TESTS][NMS_N] = {\n'
    header += array_rows([c[2] for c in cases], lambda x:str(int(x)))+'\n};\n'
    for field, index in [('NMS_TEST_LIMIT', 3), ('NMS_TEST_USED', 4)]:
        header += 'static const unsigned int '+field+'[NMS_NUM_TESTS] = {'+', '.join(str(c[index]) for c in cases)+'};\n'
    header += '#endif\n'
    (root/'nms_vectors.h').write_text(header, encoding='utf-8')
    metadata = dict(n=384, k=194, m=192, edges=1152, alpha=.75, tests=len(cases),
                    max_iteration_limits=[0, 1, 2, 5, 20],
                    matrix_seed=5203, noise_seed=2026,
                    reference_sha256=hashlib.sha256(args.reference.read_bytes()).hexdigest(),
                    note='Expected results are actual Python NMS decisions, not transmitted ground truth. Early exit matches frozen decisions.')
    (root/'vectors_metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print(f'Generated nms_tables.h and nms_vectors.h: {len(cases)} reference cases.')


if __name__ == '__main__': main()
