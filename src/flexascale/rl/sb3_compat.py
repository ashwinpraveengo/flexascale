"""
Stable-Baselines3 / PyTorch loading compatibility.

SB3 hands ``torch.load`` the member stream of the model zip (``zipfile.ZipExtFile``).
With PyTorch 2.13 on Windows that stream fails inside PyTorch's own zip reader
("PytorchStreamReader failed reading file .data/serialization_id: file read failed"),
although the archive is intact (every CRC checks) and the same bytes load from memory.
Buffering the member into ``io.BytesIO`` first fixes it and changes nothing else: the
bytes ``torch.load`` sees are identical. Linux was never affected; the buffering is
harmless there.

Installed once, idempotently, when ``flexascale.rl`` is imported.
"""

from __future__ import annotations

import functools
import io
import zipfile

import torch

_MARK = "_flexascale_buffers_zip_members"


def install() -> None:
    if getattr(torch.load, _MARK, False):
        return
    original = torch.load

    @functools.wraps(original)
    def load(f, *args, **kwargs):
        if isinstance(f, zipfile.ZipExtFile):
            f = io.BytesIO(f.read())
        return original(f, *args, **kwargs)

    setattr(load, _MARK, True)
    torch.load = load


install()
