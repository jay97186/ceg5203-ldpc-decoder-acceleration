"""Image -> LDPC(384,194) -> BPSK/AWGN -> image, using the teammate's code tables."""
from dataclasses import dataclass
from pathlib import Path
import math
import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
N, K, M = 384, 194, 192

class Codec:
    def __init__(self, directory=ROOT / "assets" / "code"):
        directory = Path(directory)
        self.info = np.fromfile(directory / "info.i32", dtype="<i4")
        self.pivots = np.fromfile(directory / "pivots.i32", dtype="<i4")
        self.parity_map = np.fromfile(directory / "parity_map.u8", dtype="u1").reshape(190, K)
        self.checks = np.fromfile(directory / "checks.i32", dtype="<i4").reshape(M, 6)
        self.edges = np.fromfile(directory / "variable_edges.i32", dtype="<i4").reshape(N, 3)
        if self.info.size != K or self.pivots.size != N-K:
            raise ValueError("LDPC code table size mismatch")
        if not np.array_equal(np.sort(np.r_[self.info, self.pivots]), np.arange(N)):
            raise ValueError("Invalid information/parity positions")

    def encode(self, bits):
        bits = np.asarray(bits, dtype=np.uint8).reshape(-1)
        padding = (-bits.size) % K
        messages = np.pad(bits, (0, padding)).reshape(-1, K)
        words = np.zeros((len(messages), N), dtype=np.uint8)
        words[:, self.info] = messages
        # uint8 arithmetic may wrap mod 256; low-bit parity is unchanged.
        words[:, self.pivots] = (messages @ self.parity_map.T) & 1
        if self.unsatisfied(words):
            raise ValueError("Generated codeword does not satisfy the FPGA parity checks")
        return words

    def payload(self, words, count):
        return np.asarray(words, dtype=np.uint8)[:, self.info].reshape(-1)[:count]

    def unsatisfied(self, words):
        parity = np.bitwise_xor.reduce(np.asarray(words)[:, self.checks], axis=2)
        return int(np.count_nonzero(np.any(parity, axis=1)))

    def reference(self, llr, limit):
        """Float32 flooding NMS oracle for verification; never a hardware fallback."""
        outputs = []
        for offset in range(0, len(llr), 256):
            x = np.clip(llr[offset:offset+256], -30, 30).astype(np.float32)
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
                incoming = r.reshape(-1, M*6)[:, self.edges]
                total = (incoming[:, :, 0] + incoming[:, :, 1]) + incoming[:, :, 2]
                posterior = x + total
                updated_q = np.clip(posterior[:, self.checks] - r, -30, 30)
                words = np.where(active[:, None], posterior < 0, words).astype(np.uint8)
                q = np.where(active[:, None, None], updated_q, q)
            outputs.append(words)
        return np.concatenate(outputs)

@dataclass
class ImageInput:
    image: Image.Image
    payload_bits: np.ndarray
    encoded: np.ndarray
    llr: np.ndarray
    received: Image.Image
    sigma: float
    ebn0_db: float
    seed: int

def prepare_image(path, codec, bound=(128, 96), ebn0_db=3.0, seed=2026, no_noise=False):
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    image = ImageOps.contain(image, bound, Image.Resampling.LANCZOS)
    pixels = np.asarray(image, dtype=np.uint8)
    bits = np.unpackbits(pixels.reshape(-1), bitorder="big")
    encoded = codec.encode(bits)
    sigma = math.sqrt(1.0 / (2.0 * (K / N) * 10.0 ** (float(ebn0_db) / 10.0)))
    symbols = np.float32(1) - np.float32(2) * encoded.astype(np.float32)
    if no_noise:
        llr = symbols * np.float32(30)
        sigma = 0.0
    else:
        noise = np.random.default_rng(int(seed)).normal(0, sigma, symbols.shape).astype(np.float32)
        received = symbols + noise
        llr = np.clip(np.float32(2.0 / (sigma * sigma)) * received, -30, 30).astype("<f4")
    received_image = reconstruct(codec, (llr < 0).astype(np.uint8), image.size)
    return ImageInput(image, bits, encoded, llr, received_image, sigma, float(ebn0_db), int(seed))

def reconstruct(codec, words, size):
    width, height = size
    bits = codec.payload(words, width * height * 24)
    pixels = np.packbits(bits, bitorder="big").reshape(height, width, 3)
    return Image.fromarray(pixels)

def evaluate(codec, data, words):
    words = np.asarray(words, dtype=np.uint8).reshape(-1, N)
    if words.shape != data.encoded.shape or np.any(words > 1):
        raise ValueError("Invalid FPGA output shape or bit value")
    payload = codec.payload(words, data.payload_bits.size)
    errors = int(np.count_nonzero(payload != data.payload_bits))
    image = reconstruct(codec, words, data.image.size)
    mse = float(np.mean((np.asarray(image, dtype=np.float64) -
                         np.asarray(data.image, dtype=np.float64)) ** 2))
    return image, {
        "payload_bit_errors": errors,
        "payload_ber": errors / data.payload_bits.size,
        "codeword_bit_errors": int(np.count_nonzero(words != data.encoded)),
        "unsatisfied_frames": codec.unsatisfied(words),
        "psnr_db": None if mse == 0 else 10 * math.log10(255 * 255 / mse),
        "exact_image": mse == 0,
    }
