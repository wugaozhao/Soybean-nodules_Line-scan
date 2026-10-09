"""Utilities for tiled processing of very large images."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class Tile:
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0


def _starts(length: int, tile_size: int, stride: int) -> list[int]:
    if tile_size <= 0:
        raise ValueError("tile_size must be positive")
    if stride <= 0:
        raise ValueError("stride must be positive")
    if length <= tile_size:
        return [0]

    starts = list(range(0, length - tile_size + 1, stride))
    last = length - tile_size
    if starts[-1] != last:
        starts.append(last)
    return starts


def iter_tiles(width: int, height: int, tile_size: int, stride: int) -> Iterator[Tile]:
    """Yield tile boxes that cover the full image, including right/bottom edges."""
    for y0 in _starts(height, tile_size, stride):
        y1 = min(y0 + tile_size, height)
        for x0 in _starts(width, tile_size, stride):
            x1 = min(x0 + tile_size, width)
            yield Tile(x0=x0, y0=y0, x1=x1, y1=y1)

