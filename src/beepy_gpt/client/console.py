"""Which characters the Linux console font can draw (the Beepy's fbcon font has 256)."""

from __future__ import annotations

import ctypes
import errno
import fcntl
from typing import Optional

GIO_UNIMAP = 0x4B66  # linux/kd.h: read the console font's Unicode map


class _UniPair(ctypes.Structure):
    _fields_ = [("unicode", ctypes.c_ushort), ("fontpos", ctypes.c_ushort)]


class _UniMapDesc(ctypes.Structure):
    _fields_ = [("entry_ct", ctypes.c_ushort), ("entries", ctypes.POINTER(_UniPair))]


def console_glyphs(fd: int = 0) -> Optional[frozenset]:
    """Code points the console font on `fd` maps, or None if `fd` is not a Linux console."""
    count = 512
    for _ in range(3):
        pairs = (_UniPair * count)()
        desc = _UniMapDesc(count, ctypes.cast(pairs, ctypes.POINTER(_UniPair)))
        try:
            fcntl.ioctl(fd, GIO_UNIMAP, desc)
        except OSError as e:
            if e.errno == errno.ENOMEM and desc.entry_ct > count:
                count = desc.entry_ct  # the kernel reports how many entries it has
                continue
            return None
        if desc.entry_ct == 0:
            return None
        return frozenset(pairs[i].unicode for i in range(desc.entry_ct))
    return None
