import numpy as np
import ldpc_bf_image_sim as m

code = m.make_code()
rng = np.random.default_rng(99)
q = rng.integers(-7, 8, (2, code['checks'].shape[0], 6)).astype(np.float32)
actual = m.nms_check_update(q)
expected = np.zeros_like(q)
for frame in range(2):
    for check in range(q.shape[1]):
        for lane in range(6):
            others = np.delete(q[frame, check], lane)
            expected[frame, check, lane] = .75*np.prod(np.where(others < 0, -1, 1))*np.min(np.abs(others))
assert np.array_equal(actual, expected), 'Check-node exclusion/ties/sign failed'

llr = rng.normal(0, 3, (2, 384)).astype(np.float32)
words = (llr < 0).astype(np.uint8)
q = llr[:, code['checks']].copy()
for iteration in range(3):
    r = m.nms_check_update(q)
    posterior = llr.copy()
    for check, neighbors in enumerate(code['checks']):
        for lane, variable in enumerate(neighbors):
            posterior[:, variable] += r[:, check, lane]
    ref_q = np.clip(posterior[:, code['checks']]-r, -30, 30)
    active = np.any(m.syndrome(words, code['checks']), axis=1)
    ref_words = np.where(active[:, None], (posterior < 0).astype(np.uint8), words)
    ref_q = np.where(active[:, None, None], ref_q, q)
    new_words, new_q = m.nms_step(llr, q, words, code)
    assert np.array_equal(new_words, ref_words)
    assert np.allclose(new_q, ref_q, atol=1e-5)
    words, q = new_words, new_q

sent = m.encode(rng.integers(0, 2, len(code['info'])*8, dtype=np.uint8), code)
for channel in ['none', 'bsc', 'awgn']:
    rx, config, llr = m.apply_channel(sent, channel=channel, p=0., ebn0_db=60., rate=194/384, seed=1, return_llr=True)
    words = (llr < 0).astype(np.uint8)
    words2, _ = m.nms_step(llr, llr[:, code['checks']], words, code)
    assert np.array_equal(sent, words2)
for p in [0., .01, .5, .9, 1.]:
    rx, _, llr = m.apply_channel(sent, channel='bsc', p=p, ebn0_db=6, rate=.5, seed=1, return_llr=True)
    assert np.isfinite(llr).all()
    if p == 1: assert np.array_equal((llr < 0).astype(np.uint8), sent)
print('PASS: independent scalar CNU (ties/zeros/signs), 3-step VNU/extrinsic reference, clean frame freeze, finite LLR endpoints.')
