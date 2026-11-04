"""Image -> systematic QC-LDPC -> channel LLR -> normalized min-sum (or BF).

Dependencies: numpy, Pillow; opencv-python for camera capture.
Run without --image to choose camera capture or an existing image.
This is a teaching code, not an IEEE/5G standard or an accelerator benchmark.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path
from time import perf_counter

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps


def make_code(z=64, seed=5203):
    """3x6 circulant blocks: column degree 3, row degree 6, no 4-cycles.

    GF(2) elimination is encoder setup only. Decoder uses adjacency tables,
    NOT dense H multiplication. Rank determines the actual information size.
    """
    rng = np.random.default_rng(seed)
    shifts = np.zeros((3, 6), dtype=np.int32)
    for col in range(6):
        for attempt in range(100000):
            candidate = rng.integers(0, z, size=3)
            if all(not np.any((shifts[a, :col] - shifts[b, :col]) % z ==
                              (candidate[a] - candidate[b]) % z)
                   for a in range(3) for b in range(a)):
                shifts[:, col] = candidate
                break
        else:
            raise ValueError('Could not construct QC shifts; use z >= 32.')
    h = np.zeros((3*z, 6*z), dtype=np.uint8)
    for row in range(3):
        for col in range(6):
            h[row*z + np.arange(z), col*z + (np.arange(z)+shifts[row, col]) % z] = 1
    rref = h.copy()
    pivots = []
    for col in range(h.shape[1]):
        matches = np.flatnonzero(rref[len(pivots):, col])
        if not matches.size:
            continue
        row = len(pivots)
        other = row + int(matches[0])
        rref[[row, other]] = rref[[other, row]]
        targets = np.flatnonzero(rref[:, col])
        targets = targets[targets != row]
        rref[targets] ^= rref[row]
        pivots.append(col)
        if len(pivots) == h.shape[0]:
            break
    pivots = np.asarray(pivots, dtype=np.int32)
    info = np.setdiff1d(np.arange(h.shape[1]), pivots).astype(np.int32)
    checks = np.stack([np.flatnonzero(row) for row in h]).astype(np.int32)
    variables = np.stack([np.flatnonzero(h[:, col]) for col in range(h.shape[1])]).astype(np.int32)
    edge_ids = np.full(h.shape, -1, dtype=np.int32)
    edge_ids[np.arange(len(checks))[:, None], checks] = np.arange(checks.size).reshape(checks.shape)
    variable_edges = edge_ids[variables, np.arange(h.shape[1])[:, None]]
    return dict(H=h, shifts=shifts, pivots=pivots, info=info,
                parity_map=rref[:len(pivots), info], checks=checks, variables=variables,
                variable_edges=variable_edges)


def encode(data, code):
    k = len(code['info'])
    padded = np.pad(data, (0, (-data.size) % k)).reshape(-1, k)
    words = np.zeros((len(padded), code['H'].shape[1]), dtype=np.uint8)
    words[:, code['info']] = padded
    # uint8 wraparound preserves parity (mod 256 followed by mod 2).
    words[:, code['pivots']] = (padded @ code['parity_map'].T) & 1
    return words


def syndrome(words, checks):
    # Fixed small degree loop, parallel across all checks and frames.
    s = np.zeros((len(words), len(checks)), dtype=np.uint8)
    for lane in range(checks.shape[1]):
        s ^= words[:, checks[:, lane]]
    return s


def bf_step(words, code):
    """Strict majority: flip when 2*unsatisfied > degree; all flips simultaneous.

    Only syndrome is used to decide flips. Ground truth is NEVER decoder input.
    Zero-syndrome frames naturally freeze, even if they are wrong codewords.
    """
    s = syndrome(words, code['checks'])
    counts = np.zeros(words.shape, dtype=np.uint8)
    for lane in range(code['variables'].shape[1]):
        counts += s[:, code['variables'][:, lane]]
    return words ^ (2*counts > code['variables'].shape[1]).astype(np.uint8)


def nms_check_update(q, alpha=.75):
    """Flooding CNU: exclude destination edge; ties correctly use second min."""
    magnitudes = np.abs(q)
    minimum_index = np.argmin(magnitudes, axis=2)
    minima = np.partition(magnitudes, 1, axis=2)[:, :, :2]
    lane = np.arange(q.shape[2])[None, None, :]
    outgoing_magnitude = np.where(lane == minimum_index[:, :, None],
                                  minima[:, :, 1, None], minima[:, :, 0, None])
    negative = q < 0
    outgoing_negative = np.logical_xor(np.logical_xor.reduce(negative, axis=2)[:, :, None], negative)
    return (alpha*outgoing_magnitude*np.where(outgoing_negative, -1., 1.)).astype(np.float32)


def nms_step(llr, q, words, code, alpha=.75, clip=30.):
    """One flooding iteration, per-frame parity-based freezing. No ground truth."""
    active = np.any(syndrome(words, code['checks']), axis=1)
    r = nms_check_update(q, alpha)
    posterior = llr + r.reshape(len(llr), -1)[:, code['variable_edges']].sum(axis=2)
    candidate = (posterior < 0).astype(np.uint8)
    new_q = np.clip(posterior[:, code['checks']] - r, -clip, clip)
    return (np.where(active[:, None], candidate, words),
            np.where(active[:, None, None], new_q, q))


def font(size=20):
    try:
        return ImageFont.truetype('arial.ttf', size)
    except OSError:
        return ImageFont.load_default(size=size)


def plot_ber(records, path, decoder='nms', bf_records=None):
    """Standalone PNG plot using Pillow, so matplotlib is not required."""
    canvas = Image.new('RGB', (1100, 680), 'white')
    draw = ImageDraw.Draw(canvas)
    left, top, right, bottom = 110, 145, 1030, 550
    ymax = max(max(r['payload_ber'], r['codeword_ber']) for r in records)*1.12
    ymax = max(ymax, 0.001)
    if bf_records is not None:
        ymax = max(ymax, max(r['payload_ber'] for r in bf_records)*1.12)
    xmax = max(1, records[-1]['iteration'])
    draw.text((110, 25), f'LDPC {decoder.upper()}: BER vs iteration', fill='black', font=font(28))
    for tick in range(6):
        y = bottom-(bottom-top)*tick/5
        draw.line((left, y, right, y), fill='#dddddd')
        draw.text((12, y-12), f'{ymax*tick/5:.4f}', fill='black', font=font(18))
    ticks = sorted(set(round(xmax*i/10) for i in range(11)))
    for tick in ticks:
        x = left+(right-left)*tick/xmax
        draw.text((x-8, bottom+12), str(tick), fill='black', font=font(18))
    draw.line((left, top, left, bottom, right, bottom), fill='black', width=2)
    draw.text((15, 60), 'BER', fill='black', font=font(22))
    draw.text((500, 600), 'Iteration', fill='black', font=font(24))
    series = [
        (records, 'payload_ber', '#1267c4', f'{decoder.upper()} image payload BER', 70),
        (records, 'codeword_ber', '#d65f00', f'{decoder.upper()} full codeword BER', 95)]
    if bf_records is not None:
        series.append((bf_records, 'payload_ber', '#ad2585', 'BF image payload BER (same channel)', 120))
    for source, key, color, label, legend_y in series:
        points = [(left+(right-left)*r['iteration']/xmax,
                   bottom-(bottom-top)*r[key]/ymax) for r in source]
        if len(points) > 1:
            draw.line(points, fill=color, width=3)
        for x, y in points:
            draw.ellipse((x-3, y-3, x+3, y+3), fill=color)
        draw.line((550, legend_y, 585, legend_y), fill=color, width=3)
        draw.text((595, legend_y-12), label, fill=color, font=font(16))
    canvas.save(path)


def comparison(images, labels, path):
    cols = min(4, len(images))
    rows = (len(images)+cols-1)//cols
    sheet = Image.new('RGB', (cols*300, rows*350), '#eeeeee')
    draw = ImageDraw.Draw(sheet)
    for idx, (im, label) in enumerate(zip(images, labels)):
        x, y = (idx % cols)*300, (idx//cols)*350
        thumb = ImageOps.contain(im.convert('RGB'), (280, 280))
        sheet.paste(thumb, (x+(300-thumb.width)//2, y+15+(280-thumb.height)//2))
        draw.multiline_text((x+10, y+300), label, fill='black', font=font(16))
    sheet.save(path)


def apply_channel(sent, *, channel, p, ebn0_db, rate, seed, return_llr=False):
    """BPSK Es=1; Eb is per information bit, sigma^2=1/(2*R*Eb/N0)."""
    rng = np.random.default_rng(seed)
    if channel == 'bsc':
        if not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError('BSC probability must be between 0 and 1.')
        rx = sent ^ (rng.random(sent.shape) < p).astype(np.uint8)
        if p == 0:
            scale = 30.
        elif p == 1:
            scale = -30.
        else:
            scale = float(np.clip(math.log((1-p)/p), -30, 30))
        llr = ((1.-2.*rx.astype(np.float32))*scale).astype(np.float32)
        config = dict(channel='bsc', requested_flip_probability=p,
                      theoretical_hard_decision_ber=p)
        return (rx, config, llr) if return_llr else (rx, config)
    if channel == 'awgn':
        if not math.isfinite(ebn0_db) or not -30 <= ebn0_db <= 60:
            raise ValueError('Eb/N0 must be finite and within -30 to 60 dB.')
        sigma = math.sqrt(1/(2*rate*10**(ebn0_db/10)))
        symbols = 1.0-2.0*sent.astype(np.float64)
        analog = symbols + rng.normal(0, sigma, size=sent.shape)
        rx = (analog < 0).astype(np.uint8)
        llr = np.clip(2*analog/(sigma*sigma), -30, 30).astype(np.float32)
        config = dict(
            channel='awgn', ebn0_db=ebn0_db, bpsk_symbol_energy=1.0,
            noise_sigma=sigma, eb_definition='energy per information bit; R=k/n',
            theoretical_hard_decision_ber=.5*math.erfc(1/(sigma*math.sqrt(2))),
            demodulation='BPSK 0->+1, 1->-1; NMS uses LLR=2*y/sigma^2; BF uses hard bits')
        return (rx, config, llr) if return_llr else (rx, config)
    if channel == 'none':
        rx = sent.copy()
        config = dict(channel='none', theoretical_hard_decision_ber=0.0)
        llr = (1.-2.*sent.astype(np.float32))*30.
        return (rx, config, llr) if return_llr else (rx, config)
    raise ValueError(f'Unknown channel: {channel}')


def simulate(image, out, *, p=.01, iterations=20, snapshots=(0, 1, 2, 5, 10, 20),
             seed=2026, z=64, batch_size=256, channel='bsc', ebn0_db=6.0,
             decoder='nms', alpha=.75, compare_bf=True, device='cpu'):
    if decoder not in ('nms', 'bf') or not 0 < alpha <= 1:
        raise ValueError('decoder must be nms/bf; require 0<alpha<=1')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    code = make_code(z)
    array = np.asarray(image, dtype=np.uint8)
    bits = np.unpackbits(array.reshape(-1))
    sent = encode(bits, code)
    assert not syndrome(sent, code['checks']).any(), 'Encoder parity check failed'
    received, channel_config, llrs = apply_channel(sent, channel=channel, p=p, ebn0_db=ebn0_db,
                                             rate=len(code['info'])/sent.shape[1], seed=seed, return_llr=True)
    channel_config['measured_channel_ber'] = float(np.mean(received != sent))
    engine = None
    backend_setup_ms = 0.
    device_info = dict(device='cpu', device_name='CPU', backend='numpy')
    if device != 'cpu':
        if device not in ('cuda', 'cuda:0'):
            raise ValueError('Device must be cpu or cuda')
        from ldpc_torch_backend import TorchDecoder
        setup_start = perf_counter()
        engine = TorchDecoder(code, decoder, alpha, 'cuda:0')
        engine.warmup(min(batch_size, 32))
        backend_setup_ms = (perf_counter()-setup_start)*1000
        device_info = engine.info()
    print(f'Decoding on {device_info["device"]}: {device_info["device_name"]} ({device_info["backend"]})', flush=True)
    chosen = sorted(set([0, iterations] + [x for x in snapshots if 0 <= x <= iterations]))
    totals = np.zeros((iterations+1, 4), dtype=np.int64)
    snapshot_bits = {i: [] for i in chosen}
    elapsed = 0.0
    initialization_seconds = 0.0
    iteration_seconds = np.zeros(iterations+1, dtype=np.float64)
    output_transfer_seconds = np.zeros(iterations+1, dtype=np.float64)
    batch_seconds = []
    k = len(code['info'])
    for start in range(0, len(sent), batch_size):
        if engine is not None: engine.sync()
        init_start = perf_counter()
        words = received[start:start+batch_size].copy()
        channel_llr = llrs[start:start+batch_size]
        q = channel_llr[:, code['checks']].copy() if decoder == 'nms' and engine is None else None
        if decoder == 'nms':
            words = (channel_llr < 0).astype(np.uint8)
        if engine is not None:
            engine.initialize(received[start:start+batch_size], channel_llr)
            engine.sync()
        init_elapsed = perf_counter()-init_start
        initialization_seconds += init_elapsed
        batch_elapsed = init_elapsed
        reference = sent[start:start+batch_size]
        valid = min(words.shape[0]*k, bits.size-start*k)
        for iteration in range(iterations+1):
            if iteration:
                if engine is not None: engine.sync()
                t0 = perf_counter()
                if engine is not None:
                    engine.step()
                    engine.sync()
                elif decoder == 'nms':
                    words, q = nms_step(channel_llr, q, words, code, alpha)
                else:
                    words = bf_step(words, code)
                step_elapsed = perf_counter()-t0
                elapsed += step_elapsed
                iteration_seconds[iteration] += step_elapsed
                batch_elapsed += step_elapsed
            if engine is not None:
                transfer_start = perf_counter()
                words = engine.host_words()
                engine.sync()
                transfer_seconds = perf_counter()-transfer_start
                output_transfer_seconds[iteration] += transfer_seconds
                if iteration == iterations: batch_elapsed += transfer_seconds
            payload = words[:, code['info']].reshape(-1)[:valid]
            expected = bits[start*k:start*k+valid]
            totals[iteration, 0] += np.count_nonzero(payload != expected)
            totals[iteration, 1] += np.count_nonzero(words != reference)
            totals[iteration, 2] += np.count_nonzero(np.any(words != reference, axis=1))
            totals[iteration, 3] += np.count_nonzero(np.any(syndrome(words, code['checks']), axis=1))
            if iteration in snapshot_bits:
                snapshot_bits[iteration].append(payload.copy())
        batch_seconds.append(batch_elapsed)
    cumulative_seconds = initialization_seconds + np.cumsum(iteration_seconds) + output_transfer_seconds
    records = [dict(iteration=i, payload_ber=float(v[0]/bits.size),
                    codeword_ber=float(v[1]/sent.size), frame_error_rate=float(v[2]/len(sent)),
                    unsatisfied_frames=int(v[3]), payload_bit_errors=int(v[0]),
                    iteration_core_ms=float(iteration_seconds[i]*1000),
                    output_transfer_ms=float(output_transfer_seconds[i]*1000),
                    cumulative_decoder_ms=float(cumulative_seconds[i]*1000))
               for i, v in enumerate(totals)]
    with (out/'ber_vs_iteration.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    image.save(out/'original.png')
    pictures, labels = [image], ['Original (before channel)']
    for iteration in chosen:
        restored = np.packbits(np.concatenate(snapshot_bits[iteration])).reshape(array.shape)
        im = Image.fromarray(restored)
        im.save(out/f'decoded_iter_{iteration:03d}.png')
        pictures.append(im)
        labels.append(f'Iteration {iteration}\nPayload BER = {records[iteration]["payload_ber"]:.6f}')
    comparison(pictures, labels, out/'iteration_comparison.png')
    plot_ber(records, out/'ber_vs_iteration.png', decoder)
    np.savez_compressed(out/'accelerator_vectors.npz', checks=code['checks'],
                        variables=code['variables'], info_indices=code['info'],
                        shifts=code['shifts'], tx=sent, rx=received,
                        original_payload=bits, parity_check_matrix=code['H'], channel_llr=llrs,
                        variable_edges=code['variable_edges'])
    metadata = dict(**channel_config, **device_info, seed=seed, matrix_seed=5203,
                    n=int(sent.shape[1]), k=k, m=int(code['H'].shape[0]),
                    rate=k/sent.shape[1], z=z, frames=len(sent), iterations=iterations, snapshots=chosen,
                    image_mode=image.mode, image_shape=list(array.shape),
                    padding_bits=len(sent)*k-bits.size, batch_size=batch_size,
                    decoder=decoder, schedule='flooding' if decoder == 'nms' else 'synchronous parallel',
                    alpha=alpha if decoder == 'nms' else None, llr_clip=30.,
                    early_stop='per-frame zero syndrome; frozen frames retained in later snapshots',
                    decoder_step_seconds=elapsed,
                    backend_setup_and_warmup_ms=backend_setup_ms,
                    final_device_to_host_ms=float(output_transfer_seconds[-1]*1000),
                    diagnostic_device_to_host_ms=float(output_transfer_seconds[:-1].sum()*1000),
                    decoder_initialization_seconds=initialization_seconds,
                    decoder_total_ms=float(cumulative_seconds[-1]*1000),
                    amortized_us_per_codeword=float(cumulative_seconds[-1]*1e6/len(sent)),
                    mean_batch_decoder_ms=float(np.mean(batch_seconds)*1000),
                    p95_batch_decoder_ms=float(np.percentile(batch_seconds, 95)*1000),
                    batch_count=len(batch_seconds),
                    timing_note='Synchronized wall time: batch initialization (CUDA input transfer included), iteration calls and final output transfer. Excludes backend setup/warmup, graph upload, channel/LLR generation, intermediate diagnostic D2H copies, metrics and plots. Intermediate diagnostics perturb execution; not an isolated production throughput benchmark. Amortized us/codeword is NOT single-frame latency.',
                    timing_iteration_policy='Fixed iteration budget; zero-syndrome frames frozen but vectorized calls continue through max iterations.',
                    warning='Educational custom QC code; no near-capacity claim. BER is not guaranteed monotonic.',
                    numpy_version=np.__version__)
    (out/'run_config.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print(f'QC-LDPC n={sent.shape[1]}, k={k}, frames={len(sent)}, channel={channel}, decoder={decoder}')
    print(f'Channel settings: {channel_config}')
    for i in chosen:
        print(f'iteration {i:3d}: payload BER={records[i]["payload_ber"]:.6f}, FER={records[i]["frame_error_rate"]:.6f}')
    print(f'[{decoder.upper()} timing] total decoder = {metadata["decoder_total_ms"]:.3f} ms; '
          f'mean batch = {metadata["mean_batch_decoder_ms"]:.3f} ms; '
          f'p95 batch = {metadata["p95_batch_decoder_ms"]:.3f} ms; '
          f'amortized = {metadata["amortized_us_per_codeword"]:.3f} us/codeword')
    print('Timing excludes channel, BER calculation and plotting; amortized time is not single-frame latency.')
    print(f'Output: {out.resolve()}')
    if decoder == 'nms' and compare_bf:
        bf_records = simulate(image, out/'bf_baseline', p=p, iterations=iterations,
                              snapshots=snapshots, seed=seed, z=z, batch_size=batch_size,
                              channel=channel, ebn0_db=ebn0_db, decoder='bf', compare_bf=False, device=device)
        plot_ber(records, out/'decoder_comparison.png', decoder, bf_records)
        bf_metadata = json.loads((out/'bf_baseline'/'run_config.json').read_text(encoding='utf-8'))
        timing_rows = []
        for config, rows in [(metadata, records), (bf_metadata, bf_records)]:
            timing_rows.append({key: config[key] for key in [
                'decoder', 'device', 'backend', 'frames', 'iterations', 'batch_size', 'decoder_total_ms',
                'mean_batch_decoder_ms', 'p95_batch_decoder_ms', 'amortized_us_per_codeword']})
            timing_rows[-1].update(final_payload_ber=rows[-1]['payload_ber'],
                                   final_fer=rows[-1]['frame_error_rate'])
        with (out/'latency_comparison.csv').open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=list(timing_rows[0]))
            writer.writeheader()
            writer.writerows(timing_rows)
        print(f'\n=== NMS vs BF: {device_info["device"]} / {device_info["device_name"]}, same channel sample ===')
        print('Decoder | Total (ms) | Mean batch (ms) | P95 batch (ms) | Amortized (us/codeword) | Final BER')
        for row in timing_rows:
            print(f'{row["decoder"].upper():7s} | {row["decoder_total_ms"]:10.3f} | '
                  f'{row["mean_batch_decoder_ms"]:15.3f} | {row["p95_batch_decoder_ms"]:14.3f} | '
                  f'{row["amortized_us_per_codeword"]:22.3f} | {row["final_payload_ber"]:.6f}')
        print('Fixed iteration budget; per-frame convergence freezes decisions, not all batch computation.')
    return records


def self_test():
    code = make_code()
    rng = np.random.default_rng(1)
    payload = rng.integers(0, 2, len(code['info'])*16-3, dtype=np.uint8)
    sent = encode(payload, code)
    assert not syndrome(sent, code['checks']).any()
    assert np.array_equal(sent[:, code['info']].reshape(-1)[:payload.size], payload)
    assert np.array_equal(bf_step(sent, code), sent)
    for bit in range(sent.shape[1]):
        damaged = sent[:1].copy()
        damaged[0, bit] ^= 1
        assert np.array_equal(bf_step(damaged, code), sent[:1]), f'Single error failed: {bit}'
    damaged = sent.copy()
    damaged[:, ::37] ^= 1
    s = (damaged @ code['H'].T) & 1
    counts = s.astype(np.int32) @ code['H'].astype(np.int32)
    expected = damaged ^ (2*counts > 3).astype(np.uint8)
    assert np.array_equal(bf_step(damaged, code), expected)
    assert np.array_equal(syndrome(damaged, code['checks']), s)
    print('PASS: encoding, payload/padding, clean frames, every single-bit location, dense-reference BF.')


def parse_iteration_settings(iterations_text, snapshots_text):
    """Validate the initial dialog's maximum and comparison image iterations."""
    try:
        maximum = int(str(iterations_text).strip())
    except (ValueError, TypeError):
        raise ValueError('最大迭代次數必須是大於或等於 0 的整數。') from None
    if maximum < 0:
        raise ValueError('最大迭代次數必須是大於或等於 0 的整數。')
    tokens = [token for token in re.split(r'[\s,，、;；]+', str(snapshots_text).strip()) if token]
    try:
        selected = [int(token) for token in tokens]
    except ValueError:
        raise ValueError('比較輪次請輸入整數，以逗號或空白分隔，例如 0, 1, 3, 5, 10, 30。') from None
    if any(value < 0 for value in selected):
        raise ValueError('比較輪次不能小於 0。')
    if any(value > maximum for value in selected):
        raise ValueError('比較輪次不能超過最大迭代次數；請提高最大值或調整比較輪次。')
    return maximum, sorted(set([0, maximum] + selected))


def choose_channel_settings(p=.01, ebn0_db=6.0, decoder='nms', alpha=.75, device='cpu',
                            iterations=20, snapshots=(0, 1, 2, 5, 10, 20)):
    """Channel selection precedes image/camera selection. Cancel writes nothing."""
    from tkinter import Tk, Label, Button, Frame, StringVar, Radiobutton, Entry, messagebox
    root = Tk()
    root.title('LDPC - 通道與解碼器設定')
    root.resizable(False, False)
    result = None
    channel = StringVar(value='bsc')
    probability = StringVar(value=str(p))
    snr = StringVar(value=str(ebn0_db))
    algorithm = StringVar(value=decoder)
    scaling = StringVar(value=str(alpha))
    compute = StringVar(value='cuda' if device.startswith('cuda') else 'cpu')
    iteration_limit = StringVar(value=str(iterations))
    comparison_rounds = StringVar(value=', '.join(
        str(value) for value in sorted(set([0, iterations] +
            [value for value in snapshots if 0 <= value <= iterations]))))
    Label(root, text='選擇 Channel Noise', font=('Microsoft JhengHei', 17)).pack(pady=14, padx=25)
    body = Frame(root)
    body.pack(padx=25, pady=8)
    Radiobutton(body, text='BSC：每個位元獨立翻轉', variable=channel, value='bsc').grid(row=0, column=0, sticky='w')
    Label(body, text='翻轉機率 p（0～1）').grid(row=1, column=0, sticky='w', padx=24)
    p_entry = Entry(body, textvariable=probability, width=16)
    p_entry.grid(row=1, column=1, pady=6)
    Radiobutton(body, text='AWGN：BPSK＋高斯雜訊', variable=channel, value='awgn').grid(row=2, column=0, sticky='w')
    Label(body, text='Eb/N0（dB，-30～60）').grid(row=3, column=0, sticky='w', padx=24)
    snr_entry = Entry(body, textvariable=snr, width=16)
    snr_entry.grid(row=3, column=1, pady=6)
    Radiobutton(body, text='無雜訊：驗證編碼與解碼', variable=channel, value='none').grid(row=4, column=0, sticky='w')
    Label(body, text='解碼器').grid(row=5, column=0, sticky='w', pady=(15, 3))
    Radiobutton(body, text='NMS：軟資訊 Normalized Min-Sum（推薦）', variable=algorithm, value='nms').grid(row=6, column=0, sticky='w')
    Radiobutton(body, text='BF：原本的硬判決基準', variable=algorithm, value='bf').grid(row=7, column=0, sticky='w')
    Label(body, text='NMS 縮放係數 alpha（0 < alpha ≤ 1）').grid(row=8, column=0, sticky='w', padx=24)
    Entry(body, textvariable=scaling, width=16).grid(row=8, column=1, pady=6)
    Label(body, text='迭代與圖片比較').grid(row=9, column=0, sticky='w', pady=(12, 3))
    Label(body, text='最大迭代次數（可設 0、20、30…）').grid(row=10, column=0, sticky='w', padx=24)
    Entry(body, textvariable=iteration_limit, width=16).grid(row=10, column=1, pady=6)
    Label(body, text='要比較的輪次（逗號或空白分隔）').grid(row=11, column=0, sticky='w', padx=24)
    Entry(body, textvariable=comparison_rounds, width=28).grid(row=11, column=1, pady=6)
    Label(body, text='例如 0, 1, 3, 5, 10, 30；自動包含第 0 輪與最後一輪。\n留空只比較第 0 輪與最後一輪；各輪使用同一份通道雜訊。',
          justify='left').grid(row=12, column=0, columnspan=2, sticky='w', padx=24, pady=(0, 5))
    Label(body, text='運算裝置').grid(row=13, column=0, sticky='w', pady=(12, 3))
    Radiobutton(body, text='CPU（NumPy）', variable=compute, value='cpu').grid(row=14, column=0, sticky='w')
    Radiobutton(body, text='GPU（NVIDIA CUDA / PyTorch）', variable=compute, value='cuda').grid(row=15, column=0, sticky='w')
    Label(root, text='BSC：p 越小越乾淨，例如 0.001、0.005、0.01\nAWGN：Eb/N0 越大越乾淨；以資訊位元能量定義\n完整碼字經通道後，NMS 使用 LLR，BF 使用硬判決。',
          justify='left').pack(padx=25, pady=10)
    Label(root, text='NMS 保留 AWGN 可信度；預設同時產生 BF 對照結果。').pack()

    def update_entries(*_):
        p_entry.configure(state='normal' if channel.get() == 'bsc' else 'disabled')
        snr_entry.configure(state='normal' if channel.get() == 'awgn' else 'disabled')

    def confirm():
        nonlocal result
        selected = channel.get()
        pp, db = p, ebn0_db
        try:
            max_iterations, selected_snapshots = parse_iteration_settings(
                iteration_limit.get(), comparison_rounds.get())
            aa = float(scaling.get())
            if not math.isfinite(aa) or not 0 < aa <= 1:
                raise ValueError('alpha 必須大於 0 且不超過 1。')
            if compute.get() == 'cuda':
                try:
                    import torch
                    if not torch.cuda.is_available():
                        raise ValueError('找不到可用 CUDA GPU。請檢查 NVIDIA 驅動與 CUDA 版 PyTorch，或選 CPU。')
                except ImportError:
                    raise ValueError('目前 Python 未安裝 PyTorch；請使用專案啟動檔或先安裝 CUDA 版 PyTorch。')
            if selected == 'bsc':
                pp = float(probability.get())
                if not math.isfinite(pp) or not 0 <= pp <= 1:
                    raise ValueError('BSC 翻轉機率必須介於 0 與 1。')
            elif selected == 'awgn':
                db = float(snr.get())
                if not math.isfinite(db) or not -30 <= db <= 60:
                    raise ValueError('Eb/N0 必須介於 -30 與 60 dB。')
        except ValueError as error:
            messagebox.showerror('設定錯誤', str(error), parent=root)
            return
        result = dict(channel=selected, p=pp, ebn0_db=db, decoder=algorithm.get(),
                      alpha=aa, device=compute.get(), iterations=max_iterations,
                      snapshots=selected_snapshots)
        root.destroy()

    channel.trace_add('write', update_entries)
    update_entries()
    footer = Frame(root)
    footer.pack(pady=15)
    Button(footer, text='下一步：拍照或選照片', command=confirm, width=25).pack(side='left', padx=6)
    Button(footer, text='取消', command=root.destroy, width=10).pack(side='left', padx=6)
    root.mainloop()
    return result


def choose_input_image(camera_index=0):
    """Local source selector and live camera preview; capture is explicit only."""
    import sys
    from tkinter import Tk, Label, Button, Frame, StringVar, filedialog, messagebox
    from PIL import ImageTk

    root = Tk()
    root.title('LDPC - 選擇圖片來源')
    root.geometry('820x650')
    result = None
    capture = None
    current_frame = None
    timer = None
    cv = None
    failures = 0
    status = StringVar(value='請選擇「鏡頭拍照」或「選擇照片」')
    Label(root, text='LDPC 圖片模擬', font=('Microsoft JhengHei', 18)).pack(pady=12)
    preview = Label(root, text='鏡頭預覽會顯示在這裡', bg='#202020', fg='white')
    preview.pack(fill='both', expand=True, padx=16, pady=8)
    Label(root, textvariable=status, font=('Microsoft JhengHei', 11)).pack(pady=8)
    buttons = Frame(root)
    buttons.pack(pady=12)

    def stop_camera():
        nonlocal capture, current_frame, timer
        if timer is not None:
            root.after_cancel(timer)
            timer = None
        if capture is not None:
            capture.release()
            capture = None
        current_frame = None
        shoot.configure(state='disabled')

    def finish(image=None):
        nonlocal result
        result = image
        stop_camera()
        root.destroy()

    def update_preview():
        nonlocal current_frame, timer, failures
        timer = None
        if capture is None:
            return
        ok, frame = capture.read()
        if ok:
            failures = 0
            current_frame = Image.fromarray(cv.cvtColor(frame, cv.COLOR_BGR2RGB))
            thumb = ImageOps.contain(current_frame, (760, 440))
            photo = ImageTk.PhotoImage(thumb)
            preview.configure(image=photo, text='')
            preview.image = photo
            shoot.configure(state='normal')
        else:
            current_frame = None
            shoot.configure(state='disabled')
            failures += 1
            if failures >= 30:
                stop_camera()
                status.set('鏡頭無法取得影像，請重新開啟或選擇照片。')
                messagebox.showerror('鏡頭讀取失敗', '請檢查鏡頭連線、Windows 相機權限，或是否被其他程式使用。', parent=root)
                return
        timer = root.after(40, update_preview)

    def open_camera():
        nonlocal cv, capture, failures
        stop_camera()
        try:
            vendor = str(Path(__file__).parent/'vendor')
            if Path(vendor).is_dir() and vendor not in sys.path:
                sys.path.insert(0, vendor)
            import cv2
            cv = cv2
        except ImportError as error:
            messagebox.showerror('需要 OpenCV', f'請先安裝 opencv-python：\npython -m pip install "opencv-python>=4.8,<5"\n\n{error}', parent=root)
            return
        capture = cv.VideoCapture(camera_index)
        if not capture.isOpened():
            stop_camera()
            status.set('無法開啟鏡頭；仍可選擇照片。')
            messagebox.showerror('無法開啟鏡頭', '請檢查鏡頭連線、相機權限，或用 --camera-index 1 選擇其他鏡頭。', parent=root)
            return
        failures = 0
        status.set('確認預覽後按「拍下並開始模擬」；也可以改選照片。')
        update_preview()

    def take_photo():
        if current_frame is not None:
            finish(current_frame.copy())

    def select_file():
        selected = filedialog.askopenfilename(parent=root, title='選擇照片',
            filetypes=[('Images', '*.png *.jpg *.jpeg *.bmp *.tif *.tiff'), ('All files', '*.*')])
        if selected:
            try:
                with Image.open(selected) as source:
                    image = ImageOps.exif_transpose(source).convert('RGB')
            except (OSError, ValueError) as error:
                messagebox.showerror('圖片讀取失敗', str(error), parent=root)
                return
            finish(image)

    Button(buttons, text='鏡頭拍照', command=open_camera, width=14).pack(side='left', padx=5)
    Button(buttons, text='選擇照片', command=select_file, width=14).pack(side='left', padx=5)
    shoot = Button(buttons, text='拍下並開始模擬', command=take_photo, state='disabled', width=20)
    shoot.pack(side='left', padx=5)
    Button(buttons, text='取消', command=finish, width=8).pack(side='left', padx=5)
    root.protocol('WM_DELETE_WINDOW', finish)
    try:
        root.mainloop()
    finally:
        if capture is not None:
            capture.release()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, help='Input image; omitted = camera/photo source selector')
    parser.add_argument('--camera-index', type=int, default=0, help='Camera device index (default 0)')
    parser.add_argument('--output', type=Path, default=Path(__file__).parent/'results')
    parser.add_argument('--noise', type=float, default=.01, help='BSC flip probability, default .01')
    parser.add_argument('--channel', choices=['bsc', 'awgn', 'none'], help='Channel; omitted in GUI = settings dialog')
    parser.add_argument('--ebn0-db', type=float, default=6.0, help='AWGN Eb/N0 per information bit, default 6 dB')
    parser.add_argument('--decoder', choices=['nms', 'bf'], default='nms')
    parser.add_argument('--device', choices=['cpu', 'cuda'], default='cpu', help='CPU NumPy or GPU PyTorch CUDA')
    parser.add_argument('--alpha', type=float, default=.75, help='NMS scale (0,1], default .75')
    parser.add_argument('--no-bf-comparison', action='store_true', help='Skip automatic BF baseline')
    parser.add_argument('--iterations', type=int, default=20)
    parser.add_argument('--snapshots', type=int, nargs='+', default=[0, 1, 2, 5, 10, 20])
    parser.add_argument('--seed', type=int, default=2026)
    parser.add_argument('--z', type=int, default=64, help='QC lifting size, >=32')
    parser.add_argument('--batch-size', type=int, default=256)
    parser.add_argument('--max-size', type=int, default=256, help='Maximum image side; 0 keeps original')
    parser.add_argument('--grayscale', action='store_true')
    parser.add_argument('--demo', action='store_true', help='Generate a sample image instead of selecting a file')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not 0 <= args.noise <= 1 or args.iterations < 0 or args.z < 32 or args.batch_size < 1 or args.max_size < 0:
        parser.error('Require 0<=noise<=1, iterations>=0, z>=32, batch-size>=1, max-size>=0')
    if not math.isfinite(args.ebn0_db) or not -30 <= args.ebn0_db <= 60:
        parser.error('Require finite Eb/N0 between -30 and 60 dB')
    if not math.isfinite(args.alpha) or not 0 < args.alpha <= 1:
        parser.error('Require 0 < alpha <= 1')
    if args.channel is None and not args.demo and args.image is None:
        settings = choose_channel_settings(args.noise, args.ebn0_db, args.decoder,
                                           args.alpha, args.device,
                                           args.iterations, args.snapshots)
        if settings is None:
            print('Cancelled. No files written.')
            return
        args.channel, args.noise, args.ebn0_db = settings['channel'], settings['p'], settings['ebn0_db']
        args.decoder, args.alpha = settings['decoder'], settings['alpha']
        args.device = settings['device']
        args.iterations, args.snapshots = settings['iterations'], settings['snapshots']
    args.channel = args.channel or 'bsc'
    if args.demo:
        y, x = np.mgrid[:192, :256]
        array = np.stack([x, y*255//191, (x+y)//2], axis=-1).astype(np.uint8)
        image = Image.fromarray(array)
        d = ImageDraw.Draw(image)
        d.rectangle((20, 20, 110, 100), fill='white', outline='black', width=3)
        d.ellipse((140, 70, 230, 160), fill='orange', outline='black', width=3)
        d.text((30, 125), 'LDPC BF', fill='white', font=font(24))
    elif args.image is None:
        image = choose_input_image(args.camera_index)
        if image is None:
            print('Cancelled. No files written.')
            return
    else:
        with Image.open(args.image) as source:
            image = ImageOps.exif_transpose(source).convert('RGB')
    if args.grayscale:
        image = image.convert('L')
    if args.max_size:
        image.thumbnail((args.max_size, args.max_size), Image.Resampling.LANCZOS)
    simulate(image, args.output, p=args.noise, iterations=args.iterations,
             snapshots=args.snapshots, seed=args.seed, z=args.z, batch_size=args.batch_size,
             channel=args.channel, ebn0_db=args.ebn0_db, decoder=args.decoder, alpha=args.alpha,
             compare_bf=not args.no_bf_comparison, device=args.device)


if __name__ == '__main__':
    main()
