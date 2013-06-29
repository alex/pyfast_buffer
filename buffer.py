import os
import struct
from itertools import izip

import cffi


ffi = cffi.FFI()
ffi.cdef("""
ssize_t read(int, void *, size_t);
int memcmp(const void *, const void *, size_t);
void *memchr(const void *, int, size_t);
""")
lib = ffi.verify("""
#include <string.h>
#include <unistd.h>
""")

BLOOM_WIDTH = struct.calcsize("l") * 8


class Buffer(object):
    def __init__(self, data, length):
        self._data = data
        self._length = length

    @classmethod
    def from_bytes(cls, bytes):
        return cls(ffi.new("uint8_t[]", bytes), len(bytes))

    @classmethod
    def from_fd_read(cls, fd, length):
        data = ffi.new("uint8_t[]", length)
        res = lib.read(fd, data, length)
        if res == -1:
            raise OSError(ffi.errno, os.strerror(ffi.errno))
        elif res == 0:
            raise EOFError
        return cls(data, res)

    def __len__(self):
        return self._length

    def __eq__(self, other):
        if isinstance(other, bytes):
            if len(self) != len(other):
                return False
            for c1, c2 in izip(self, other):
                if c1 != c2:
                    return False
            return True
        elif isinstance(other, Buffer):
            if len(self) != len(other):
                return False
            return lib.memcmp(self._data, other._data, len(self)) == 0
        else:
            return NotImplemented

    def __ne__(self, other):
        return not (self == other)

    def __getitem__(self, idx):
        if isinstance(idx, slice):
            (start, stop, step) = idx.indices(len(self))
            if step != 1 or start > stop:
                raise ValueError("You're an asshole")
            return type(self)(self._data + start, stop - start)
        else:
            if idx < 0:
                idx += len(self)
            if not (0 <= idx < len(self)):
                raise IndexError(idx)
            return chr(self._data[idx])

    def find(self, sub, start=0, end=None):
        end = end or self._length
        if start < 0:
            start = 0
        if end > len(self):
            end = len(self)
        if end - start < 0:
            return -1

        if len(sub) == 0:
            return start
        elif len(sub) == 1:
            pos = lib.memchr(self._data + start, ord(sub[0]), end)
            if pos == ffi.NULL:
                return -1
            else:
                return ffi.cast("uint8_t *", pos) - self._data
        else:
            mask, skip = self._make_find_mask(sub)
            return self._multi_char_find(sub, start, end, mask, skip)

    def _multi_char_find(self, sub, start, end, mask, skip):
        i = start - 1
        w = (end - start) - len(sub)
        mlast = len(sub) - 1
        while i + 1 <= start + w:
            i += 1
            if self[i + len(sub) - 1] == sub[len(sub) - 1]:
                for j in xrange(mlast):
                    if self[i + j] != sub[j]:
                        break
                else:
                    return i
                if i + len(sub) < len(self) and not self._bloom(mask, self[i + len(sub)]):
                    i += m
                else:
                    i += skip
            else:
                if i + len(sub) < len(self) and not self._bloom(mask, self[i + len(sub)]):
                    i += len(sub)
        return -1

    def _make_find_mask(self, sub):
        mlast = len(sub) - 1
        mask = 0
        skip = mlast - 1
        for i in xrange(mlast):
            mask = self._bloom_add(mask, sub[i])
            if sub[i] == sub[mlast]:
                skip = mlast - i - 1
            mask = self._bloom_add(mask, sub[mlast])
            return mask, skip

    def _bloom_add(self, mask, c):
        return mask | (1 << (ord(c) & (BLOOM_WIDTH - 1)))

    def _bloom(self, mask, c):
        return mask & (1 << (ord(c) & (BLOOM_WIDTH - 1)))