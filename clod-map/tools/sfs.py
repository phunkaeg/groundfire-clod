"""Read-only reader for the observed CloD SFS v300 block container.

Format deductions are checked against installed archive bounds and decoded sizes.
File identities are hashes, not assumed filenames. Only observed block methods
are accepted; unsupported methods fail explicitly. No game library is loaded.
LZ4 block decoding is independently implemented from the upstream format spec.
"""
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
import struct


def lz4_block(data, limit=32768):
    output = bytearray()
    pos = 0
    def length(value):
        nonlocal pos
        if value == 15:
            while True:
                if pos >= len(data):
                    raise ValueError("Truncated LZ4 length")
                more = data[pos]
                pos += 1
                value += more
                if more != 255:
                    break
        return value
    while pos < len(data):
        token = data[pos]
        pos += 1
        literal = length(token >> 4)
        if pos + literal > len(data) or len(output) + literal > limit:
            raise ValueError("LZ4 literal bounds")
        output.extend(data[pos:pos+literal])
        pos += literal
        if pos == len(data):
            break
        if pos + 2 > len(data):
            raise ValueError("Truncated LZ4 offset")
        offset = data[pos] | data[pos+1] << 8
        pos += 2
        match = length(token & 15) + 4
        if offset == 0 or offset > len(output) or len(output) + match > limit:
            raise ValueError("LZ4 match bounds")
        pattern = output[-offset:]
        output.extend((pattern * ((match+offset-1)//offset))[:match])
    return bytes(output)


@dataclass(frozen=True)
class Entry:
    finger: int
    ordinal: int
    offset: int
    size: int
    attributes: int
    flags: int
    checksum_field: int


class SFS:
    block_size = 32768
    def __init__(self, path, cache_blocks=128):
        self.path = Path(path)
        self.file = self.path.open("rb")
        try:
            self.file_size = self.path.stat().st_size
            header = self.file.read(256)
            if len(header) != 256 or header[:4] != b"SFS\0":
                raise ValueError("Not an observed SFS archive")
            version, self.header_unknown, count = struct.unpack_from("<III", header, 4)
            table_start, table_end, data_start, self.logical_size = struct.unpack_from("<QQQQ", header, 16)
            if version != 300 or table_start != 256 or table_end != table_start + count*40:
                raise ValueError("Unsupported SFS layout")
            if not table_end < data_start <= self.file_size or (data_start-table_end) % 8:
                raise ValueError("Invalid SFS block table")
            self.file.seek(table_start)
            self.entries = [Entry(*struct.unpack("<QIQQIII", self.file.read(40))) for _ in range(count)]
            block_count = (data_start-table_end)//8
            self.offsets = struct.unpack("<" + "Q"*block_count, self.file.read(block_count*8))
            if (len(self.offsets)-1 != (self.logical_size+self.block_size-1)//self.block_size
                    or self.offsets[0] != data_start or self.offsets[-1] != self.file_size
                    or any(a >= b for a,b in zip(self.offsets,self.offsets[1:]))):
                raise ValueError("Invalid SFS compressed block offsets")
            if any(e.ordinal != i or e.offset+e.size > self.logical_size for i,e in enumerate(self.entries)):
                raise ValueError("Invalid SFS entry extent/ordinal")
            self.cache = OrderedDict()
            self.cache_blocks = cache_blocks
            self.methods = set()
        except Exception:
            self.file.close()
            raise

    def close(self):
        self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def block(self, index):
        if index in self.cache:
            self.cache.move_to_end(index)
            return self.cache[index]
        a,b = self.offsets[index:index+2]
        self.file.seek(a)
        payload = self.file.read(b-a)
        method = payload[0]
        self.methods.add(method)
        if len(payload) == self.block_size:
            decoded = payload
        elif method == 3:
            decoded = lz4_block(payload[1:],self.block_size)
        else:
            raise ValueError(f"Unverified SFS block method {method}, block {index}")
        if len(decoded) != self.block_size:
            raise ValueError(f"Unexpected decoded block length {len(decoded)}")
        self.cache[index] = decoded
        if len(self.cache) > self.cache_blocks:
            self.cache.popitem(last=False)
        return decoded

    def read(self, entry, limit=None, offset=0):
        if not 0 <= offset <= entry.size:
            raise ValueError("Invalid entry-relative offset")
        length = entry.size-offset if limit is None else min(entry.size-offset,limit)
        if length < 0:
            raise ValueError("Invalid read length")
        if not length:
            return b""
        first = (entry.offset+offset) // self.block_size
        last = (entry.offset+offset+length+self.block_size-1)//self.block_size
        data = b"".join(self.block(i) for i in range(first,last))
        start = (entry.offset+offset) % self.block_size
        return data[start:start+length]
