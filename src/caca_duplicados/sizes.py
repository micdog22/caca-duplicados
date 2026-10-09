"""Tamanhos de arquivo: leitura ("1,5M") e exibição ("1,5 MB"), base 1024."""

from __future__ import annotations

import re
from decimal import Decimal

_UNITS = {
    "": 1, "B": 1,
    "K": 1024, "KB": 1024, "KIB": 1024,
    "M": 1024 ** 2, "MB": 1024 ** 2, "MIB": 1024 ** 2,
    "G": 1024 ** 3, "GB": 1024 ** 3, "GIB": 1024 ** 3,
    "T": 1024 ** 4, "TB": 1024 ** 4, "TIB": 1024 ** 4,
}
_SIZE_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*([A-Za-z]*)\s*$")


def parse_size(text: str) -> int:
    """Converte "500K", "1,5M", "2 GB" ou "1024" em bytes."""
    match = _SIZE_RE.match(text or "")
    unit = match.group(2).upper() if match else ""
    if not match or unit not in _UNITS:
        raise ValueError(f"tamanho inválido: {text!r} (use, por exemplo, 500K, 1,5M ou 2G)")
    number = Decimal(match.group(1).replace(",", "."))
    return int(number * _UNITS[unit])


def format_size(size: int) -> str:
    """Formato brasileiro: "512 bytes", "1,5 KB", "12 MB", "1,2 GB"."""
    if size < 1024:
        return f"{size:,} {'byte' if size == 1 else 'bytes'}".replace(",", ".")
    value = float(size)
    unit = "B"
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024
        if value < 1024:
            break
    text = f"{value:,.1f}".replace(",", "_").replace(".", ",").replace("_", ".")
    if text.endswith(",0"):
        text = text[:-2]
    return f"{text} {unit}"
