"""Read bytes from a plaintext ELF/SELF using the emulator's segment mapping.

This does not decrypt, patch, or modify the input. Output is local diagnostic data.
"""
import argparse
from pathlib import Path
import struct


class GuestImage:
    def __init__(self, path):
        self.data = Path(path).read_bytes()
        self.segments = []
        elf = 0
        if self.data[:4] == bytes.fromhex('4f153d1d'):
            count = struct.unpack_from('<H', self.data, 24)[0]
            elf = 32 + count * 32
            self.segments = [struct.unpack_from('<QQQQ', self.data, 32 + i * 32) for i in range(count)]
        if self.data[elf:elf + 6] != b'\x7fELF\x02\x01':
            raise ValueError('Expected a 64-bit little-endian ELF/SELF')
        phoff = struct.unpack_from('<Q', self.data, elf + 32)[0]
        stride, count = struct.unpack_from('<HH', self.data, elf + 54)
        self.headers = [struct.unpack_from('<IIQQQQQQ', self.data, elf + phoff + i * stride) for i in range(count)]

    def read(self, virtual, size):
        for index, (_, _, offset, vaddr, _, filesz, _, _) in enumerate(self.headers):
            if not (vaddr <= virtual and virtual + size <= vaddr + filesz):
                continue
            position = offset + virtual - vaddr
            if self.segments:
                match = next((s for s in self.segments if s[0] & 0x800 and (s[0] >> 20) & 0xfff == index), None)
                if match is None:
                    continue
                flags, file_offset, file_size, _ = match
                if flags & (2 | 8):
                    raise ValueError('Encrypted/compressed SELF segments are unsupported')
                position = file_offset + virtual - vaddr
            result = self.data[position:position + size]
            if len(result) != size:
                raise ValueError('Truncated segment')
            return result
        raise ValueError(f'No file-backed segment at {virtual:#x} size={size:#x}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('image', type=Path)
    parser.add_argument('address', type=lambda s: int(s, 0))
    parser.add_argument('--base', type=lambda s: int(s, 0), default=0)
    parser.add_argument('--size', type=lambda s: int(s, 0), default=256)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.write_bytes(GuestImage(args.image).read(args.address - args.base, args.size))
    print(f'Read {args.size} bytes at {args.address:#x} to {args.output}')
