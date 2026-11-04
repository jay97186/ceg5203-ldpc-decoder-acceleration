"""Compare the actual PyTorch decoder backend against NumPy, on CPU/CUDA."""
import numpy as np
import torch
import ldpc_bf_image_sim as reference
from ldpc_torch_backend import TorchDecoder
from compute_device import normalize_device, ensure_device

assert normalize_device('CPU') == 'cpu'
for alias in ['cuda', 'cuda:0', 'GPU (CUDA)', '0']:
    assert normalize_device(alias) == '0'
assert ensure_device('cpu') == 'cpu'
code = reference.make_code()
rng = np.random.default_rng(441)
payload = rng.integers(0, 2, len(code['info'])*12, dtype=np.uint8)
sent = reference.encode(payload, code)
devices = ['cpu'] + (['cuda:0'] if torch.cuda.is_available() else [])
for channel in ['bsc', 'awgn', 'none']:
    rx, _, llr = reference.apply_channel(sent, channel=channel, p=.02,
        ebn0_db=4., rate=len(code['info'])/sent.shape[1], seed=1, return_llr=True)
    for algorithm in ['nms', 'bf']:
        for device in devices:
            backend = TorchDecoder(code, algorithm, device=device)
            backend.initialize(rx, llr)
            words = (llr < 0).astype(np.uint8) if algorithm == 'nms' else rx.copy()
            q = llr[:, code['checks']].copy()
            for iteration in range(10):
                assert np.array_equal(words, backend.host_words()), (channel, algorithm, device, iteration)
                if algorithm == 'nms':
                    assert np.allclose(q, backend.q.cpu().numpy(), atol=2e-5)
                    words, q = reference.nms_step(llr, q, words, code)
                else:
                    words = reference.bf_step(words, code)
                backend.step()
            print('PASS:', channel, algorithm, device, '10 rounds vs NumPy')
if not torch.cuda.is_available():
    try: ensure_device('cuda')
    except ValueError: print('PASS: unavailable CUDA raises instead of silently falling back')
    else: raise AssertionError('CUDA fallback not allowed')
    print('CUDA device not visible: physical CUDA execution tests skipped.')
