"""Canonical Huffman image payload (pixels -> bitstream -> pixels).

Bitstream layout (MSB first):
  width u8 | height u8 | symbol_count-1 u8
  repeated symbol_count times: value u8 | code_length u4   (canonical order)
  data_bits u16 | Huffman data | CRC-16/CCITT-FALSE u16 over everything before it
"""
import heapq
from collections import Counter
import numpy as np


def _bits(value, width):
    return [(value >> (width - 1 - i)) & 1 for i in range(width)]


def _read(bits, pos, width):
    value = 0
    for b in bits[pos:pos + width]:
        value = (value << 1) | int(b)
    return value, pos + width


def crc16(bits):
    data = np.packbits(np.asarray(bits, dtype=np.uint8), bitorder='big').tobytes()
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def code_lengths(symbols):
    counts = Counter(symbols)
    if len(counts) == 1:
        return {next(iter(counts)): 1}
    heap = [(n, i, {s: 0}) for i, (s, n) in enumerate(sorted(counts.items()))]
    heapq.heapify(heap)
    tie = len(heap)
    while len(heap) > 1:
        n1, _, a = heapq.heappop(heap)
        n2, _, b = heapq.heappop(heap)
        heapq.heappush(heap, (n1 + n2, tie, {s: d + 1 for s, d in {**a, **b}.items()}))
        tie += 1
    lengths = heap[0][2]
    if max(lengths.values()) > 15:
        raise ValueError('Huffman code longer than 15 bits; header field is 4 bits')
    return lengths


def canonical(lengths):
    """Return [(value, length, code)] in canonical order."""
    order = sorted(lengths.items(), key=lambda kv: (kv[1], kv[0]))
    table, code, previous = [], 0, order[0][1]
    for value, length in order:
        code <<= length - previous
        table.append((value, length, code))
        code += 1
        previous = length
    return table


def encode(pixels, header=True):
    """header=False: send only Huffman data + CRC-16 over that data. The table,
    image size and data length are then agreed in advance (stored in the manifest)."""
    pixels = np.asarray(pixels, dtype=np.uint8)
    height, width = pixels.shape
    if not (0 < width < 256 and 0 < height < 256):
        raise ValueError('Image must be at most 255x255')
    flat = pixels.reshape(-1).tolist()
    table = canonical(code_lengths(flat))
    codes = {v: _bits(c, n) for v, n, c in table}
    data = [b for p in flat for b in codes[p]]
    if len(data) >= 1 << 16:
        raise ValueError('Huffman data longer than the 16-bit length field')
    bits = []
    if header:
        bits = _bits(width, 8) + _bits(height, 8) + _bits(len(table) - 1, 8)
        for value, length, _ in table:
            bits += _bits(value, 8) + _bits(length, 4)
        bits += _bits(len(data), 16)
    header_bits = len(bits)
    bits += data
    bits += _bits(crc16(bits), 16)
    info = dict(width=width, height=height,
                table=[dict(value=v, length=n, code=format(c, f'0{n}b')) for v, n, c in table],
                header_sent=bool(header),
                header_bits=header_bits, data_bits=len(data), crc_bits=16,
                total_bits=len(bits), raw_bits=width * height * 8)
    return np.array(bits, dtype=np.uint8), info


def decode(bits):
    """Return (pixels, crc_ok). Raises ValueError if the stream cannot be parsed."""
    bits = np.asarray(bits, dtype=np.uint8).reshape(-1)
    width, pos = _read(bits, 0, 8)
    height, pos = _read(bits, pos, 8)
    count, pos = _read(bits, pos, 8)
    lengths = {}
    for _ in range(count + 1):
        value, pos = _read(bits, pos, 8)
        length, pos = _read(bits, pos, 4)
        if length == 0 or value in lengths:
            raise ValueError('Corrupted Huffman table')
        lengths[value] = length
    data_bits, pos = _read(bits, pos, 16)
    end = pos + data_bits
    if width == 0 or height == 0 or end + 16 > bits.size:
        raise ValueError('Corrupted Huffman header')
    lookup = {(n, c): v for v, n, c in canonical(lengths)}
    out, code, length = [], 0, 0
    for b in bits[pos:end]:
        code, length = (code << 1) | int(b), length + 1
        if (length, code) in lookup:
            out.append(lookup[(length, code)])
            code, length = 0, 0
    if len(out) != width * height or length != 0:
        raise ValueError('Huffman data does not decode to width*height pixels')
    received_crc, _ = _read(bits, end, 16)
    crc_ok = received_crc == crc16(bits[:end])
    return np.array(out, dtype=np.uint8).reshape(height, width), crc_ok


def decode_known_table(bits, info, shape, fill=128):
    """Receiver already knows the code table and image size (agreed in advance).

    `info` is the dict returned by encode() at the transmitter (stored in the
    manifest). The transmitted header is ignored; only the pixel-data field and
    the CRC are read. Returns (pixels, decoded_pixel_count, crc_ok).
    The CRC is checked over the known header + received pixel data.
    """
    bits = np.asarray(bits, dtype=np.uint8).reshape(-1)
    start, count = info['header_bits'], info['data_bits']
    lookup = {(t['length'], int(t['code'], 2)): t['value'] for t in info['table']}
    image = np.full(shape[0] * shape[1], fill, dtype=np.uint8)
    n, code, length = 0, 0, 0
    for b in bits[start:start + count]:
        code, length = (code << 1) | int(b), length + 1
        if (length, code) in lookup:
            if n < image.size:
                image[n] = lookup[(length, code)]
            n += 1
            code, length = 0, 0
        elif length > 15:
            break
    # Rebuild the header exactly as the transmitter wrote it (empty if none was sent).
    header = []
    if info.get('header_sent', True):
        width, height = shape[1], shape[0]
        header = _bits(width, 8) + _bits(height, 8) + _bits(len(info['table']) - 1, 8)
        for t in info['table']:
            header += _bits(t['value'], 8) + _bits(t['length'], 4)
        header += _bits(count, 16)
    data = bits[start:start + count].tolist()
    received_crc, _ = _read(bits, start + count, 16)
    crc_ok = received_crc == crc16(header + data)
    return image.reshape(shape), min(n, image.size), bool(crc_ok)


def decode_payload(bits, info, shape):
    """Strict decode for whichever format `info` (from encode / the manifest) describes.
    Returns (pixels, crc_ok); raises ValueError if a sent header cannot be parsed."""
    if info.get('header_sent', True):
        return decode(bits)
    pixels, count, crc_ok = decode_known_table(bits, info, shape)
    return pixels, crc_ok and count == shape[0] * shape[1]


def decode_partial(bits, shape, fill=128):
    """Best-effort decode for display of an uncorrected stream.

    Returns (pixels, decoded_pixel_count, note). Pixels that cannot be decoded
    are filled with `fill`. A corrupted header gives an all-`fill` image.
    """
    bits = np.asarray(bits, dtype=np.uint8).reshape(-1)
    image = np.full(shape[0] * shape[1], fill, dtype=np.uint8)
    try:
        width, pos = _read(bits, 0, 8)
        height, pos = _read(bits, pos, 8)
        count, pos = _read(bits, pos, 8)
        lengths = {}
        for _ in range(count + 1):
            value, pos = _read(bits, pos, 8)
            length, pos = _read(bits, pos, 4)
            if length == 0 or value in lengths:
                raise ValueError('table')
            lengths[value] = length
        if (height, width) != tuple(shape):
            raise ValueError('size')
        table = canonical(lengths)
        if sum(2.0 ** -n for _, n, _ in table) > 1.0 + 1e-9:
            raise ValueError('table')
        data_bits, pos = _read(bits, pos, 16)
    except ValueError as error:
        return image.reshape(shape), 0, f'header/table corrupted ({error}); nothing decodable'
    lookup = {(n, c): v for v, n, c in table}
    end = min(pos + data_bits, bits.size)
    count_out, code, length = 0, 0, 0
    for b in bits[pos:end]:
        code, length = (code << 1) | int(b), length + 1
        if (length, code) in lookup:
            if count_out < image.size:
                image[count_out] = lookup[(length, code)]
            count_out += 1
            code, length = 0, 0
        elif length > 15:
            break
    note = 'decoded' if count_out == image.size else f'{min(count_out, image.size)}/{image.size} pixels decoded'
    return image.reshape(shape), min(count_out, image.size), note
