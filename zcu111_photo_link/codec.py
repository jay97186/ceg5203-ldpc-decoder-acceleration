"""QC-LDPC(384,194) encoder and float32 flooding Normalized Min-Sum reference decoder.

The code tables in ldpc_tables/ are the same ones used by the team's FPGA decoder
and dataset (matrix seed 5203, Z = 64, check degree 6, variable degree 3).
"""
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
N, K, M = 384, 194, 192


class Codec:
    def __init__(self, directory=ROOT / 'ldpc_tables'):
        directory = Path(directory)
        self.info = np.fromfile(directory / 'info.i32', dtype='<i4')
        self.pivots = np.fromfile(directory / 'pivots.i32', dtype='<i4')
        self.parity_map = np.fromfile(directory / 'parity_map.u8', dtype='u1').reshape(190, K)
        self.checks = np.fromfile(directory / 'checks.i32', dtype='<i4').reshape(M, 6)
        self.edges = np.fromfile(directory / 'variable_edges.i32', dtype='<i4').reshape(N, 3)
        if self.info.size != K or self.pivots.size != N - K:
            raise ValueError('LDPC code table size mismatch')
        if not np.array_equal(np.sort(np.r_[self.info, self.pivots]), np.arange(N)):
            raise ValueError('Invalid information/parity positions')

    def encode(self, bits):
        """Zero-pad to a multiple of K and return codewords [n, N]."""
        bits = np.asarray(bits, dtype=np.uint8).reshape(-1)
        messages = np.pad(bits, (0, (-bits.size) % K)).reshape(-1, K)
        words = np.zeros((len(messages), N), dtype=np.uint8)
        words[:, self.info] = messages
        # uint8 arithmetic may wrap mod 256; the low (parity) bit is unchanged.
        words[:, self.pivots] = (messages @ self.parity_map.T) & 1
        if self.unsatisfied(words):
            raise ValueError('Generated codeword does not satisfy the parity checks')
        return words

    def payload(self, words, count):
        return np.asarray(words, dtype=np.uint8)[:, self.info].reshape(-1)[:count]

    def unsatisfied(self, words):
        parity = np.bitwise_xor.reduce(np.asarray(words)[:, self.checks], axis=2)
        return int(np.count_nonzero(np.any(parity, axis=1)))

    def reference(self, llr, limit):
        """Flooding NMS, alpha 0.75, clip +-30, at most `limit` iterations.
        Each codeword stops (is frozen) once its syndrome is zero."""
        outputs = []
        for offset in range(0, len(llr), 256):
            x = np.clip(llr[offset:offset + 256], -30, 30).astype(np.float32)
            words = (x < 0).astype(np.uint8)
            q = x[:, self.checks].copy()
            for _ in range(limit):
                active = np.any(np.bitwise_xor.reduce(words[:, self.checks], axis=2), axis=1)
                if not active.any():
                    break
                magnitude = np.abs(q)
                minima = np.partition(magnitude, 1, axis=2)
                min1, min2 = minima[:, :, 0], minima[:, :, 1]
                index = np.argmin(magnitude, axis=2)
                negative = q < 0
                sign = np.logical_xor.reduce(negative, axis=2)[:, :, None] ^ negative
                r = np.float32(0.75) * np.where(
                    np.arange(6)[None, None, :] == index[:, :, None],
                    min2[:, :, None], min1[:, :, None])
                r = np.where(sign, -r, r).astype(np.float32)
                incoming = r.reshape(-1, M * 6)[:, self.edges]
                total = (incoming[:, :, 0] + incoming[:, :, 1]) + incoming[:, :, 2]
                posterior = x + total
                updated_q = np.clip(posterior[:, self.checks] - r, -30, 30)
                words = np.where(active[:, None], posterior < 0, words).astype(np.uint8)
                q = np.where(active[:, None, None], updated_q, q)
            outputs.append(words)
        return np.concatenate(outputs)
