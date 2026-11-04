"""Symbol mapping shared by the transmitter and receiver.

Complex baseband symbols S are sent as the real passband waveform
    x(n) = PEAK * Re{ S(n) * exp(j*2*pi*n/carrier_period) } = PEAK * (I cos - Q sin)
so |S| <= 1 keeps the DAC peak at PEAK.

BPSK : data bit b -> 1 - 2b                       (1 bit/symbol)
QPSK : bits (b0, b1) -> ((1-2b0) + j(1-2b1)) / sqrt2   (2 bits/symbol, Gray)
Preamble (both): bit p -> (1 - 2p) on the I axis for BPSK,
                 (1 - 2p)(1 + j)/sqrt2 for QPSK (same energy as a data symbol).
"""
import numpy as np

SQRT2 = np.sqrt(2.0)


def bits_per_symbol(kind):
    return {'BPSK': 1, 'QPSK': 2}[kind]


def map_preamble(bits, kind):
    s = 1.0 - 2.0 * np.asarray(bits, dtype=np.float64)
    return s.astype(complex) if kind == 'BPSK' else s * (1 + 1j) / SQRT2


def map_data(bits, kind):
    b = 1.0 - 2.0 * np.asarray(bits, dtype=np.float64).reshape(-1)
    if kind == 'BPSK':
        return b.astype(complex)
    if b.size % 2:
        raise ValueError('QPSK needs an even number of bits')
    return (b[0::2] + 1j * b[1::2]) / SQRT2


def packet_symbols(preamble_bits, data_bits, kind):
    return np.concatenate([map_preamble(preamble_bits, kind), map_data(data_bits, kind)])


def soft_bits(y, kind):
    """Phase-corrected complex soft symbols -> real soft value per bit (positive = bit 0)."""
    y = np.asarray(y)
    if kind == 'BPSK':
        return y.real
    return np.column_stack([y.real, y.imag]).reshape(-1)


def preamble_decisions(y, kind):
    """Hard preamble bits from soft preamble symbols."""
    y = np.asarray(y)
    metric = y.real if kind == 'BPSK' else (y * (1 - 1j)).real
    return (metric < 0).astype(np.uint8)


def passband(symbols, sps, carrier_period, peak):
    s = np.repeat(np.asarray(symbols, dtype=complex), sps)
    n = np.arange(s.size)
    return np.rint(peak * np.real(s * np.exp(2j * np.pi * (n % carrier_period) / carrier_period)))


def ideal_demod(wave, n_symbols, sps, carrier_period):
    """Coherent demodulation at the DAC rate (offline self-check only)."""
    n = np.arange(n_symbols * sps)
    z = wave[:n.size] * np.exp(-2j * np.pi * (n % carrier_period) / carrier_period)
    return 2 * z.reshape(-1, sps).mean(axis=1)
