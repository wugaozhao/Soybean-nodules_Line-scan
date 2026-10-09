"""Create fixed-size image tiles for nodule instance-segmentation labeling."""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
from pathlib import Path

import numpy as np
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE_SUFFIXES = (".bmp", ".jpg", ".jpeg", ".png", ".tif", ".tiff")


def iter_starts(length: int, tile_size: int, stride: int) -> list[int]:
    if length <= tile_size:
        return [0]
    starts = list(range(0, length - tile_size + 1, stride))
    last = length - tile_size
    if starts[-1] != last:
        starts.append(last)
    return starts


def collect_images(paths: list[str], suffixes: set[str]) -> list[Path]:
    results: list[Path] = []
    for item in paths:
        path = Path(item)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.suffix.lower() in suffixes:
                    results.append(child)
        elif path.suffix.lower() in suffixes:
            results.append(path)
    # A source can be supplied twice when several input directories overlap.
    return list(dict.fromkeys(results))


def source_id(image_path: Path) -> str:
    """Return a readable, collision-resistant identifier for an input image."""
    try:
        relative_path = image_path.resolve().relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        relative_path = image_path.resolve()
    source_key = relative_path.with_suffix("").as_posix()
    readable_key = re.sub(r"[^A-Za-z0-9]+", "_", source_key).strip("_")
    digest = hashlib.sha1(source_key.encode("utf-8")).hexdigest()[:10]
    return f"{readable_key}_{digest}"


def read_existing_rows(metadata_path: Path) -> dict[str, dict[str, str]]:
    if not metadata_path.exists():
        return {}
    with metadata_path.open("r", newline="", encoding="utf-8") as fh:
        return {row["tile_file"]: row for row in csv.DictReader(fh) if row.get("tile_file")}


def roi_fraction(mask_img: Image.Image, box: tuple[int, int, int, int]) -> float:
    crop = mask_img.crop(box).convert("L")
    arr = np.asarray(crop)
    return float((arr > 0).sum() / max(arr.size, 1))


def write_tile(
    image: Image.Image,
    out_path: Path,
    box: tuple[int, int, int, int],
    image_format: str,
    quality: int,
) -> None:
    tile = image.crop(box).convert("RGB")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if image_format.lower() in {"jpg", "jpeg"}:
        tile.save(out_path, quality=quality, subsampling=0)
    else:
        tile.save(out_path)


def make_tiles(args: argparse.Namespace) -> None:
    Image.MAX_IMAGE_PIXELS = None
    suffixes = {f".{extension.lstrip('.').lower()}" for extension in args.extensions}
    images = collect_images(args.inputs, suffixes)
    if not images:
        raise SystemExit("No input images found.")

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = PROJECT_ROOT / out_dir
    image_out_dir = out_dir / "images" / args.split
    metadata_path = out_dir / "annotations" / f"tiles_{args.split}.csv"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    rows_by_tile = read_existing_rows(metadata_path)

    roi_mask = None
    if args.roi_mask:
        roi_path = Path(args.roi_mask)
        if not roi_path.is_absolute():
            roi_path = PROJECT_ROOT / roi_path
        roi_mask = Image.open(roi_path).convert("L")

    ext = "jpg" if args.format.lower() in {"jpg", "jpeg"} else "png"
    rows = []
    for image_path in images:
        image_id = source_id(image_path)
        with Image.open(image_path) as image:
            image = image.convert("RGB")
            width, height = image.size
            if roi_mask is not None and roi_mask.size != image.size:
                raise ValueError(f"ROI mask size {roi_mask.size} does not match {image_path} size {image.size}")
            for y0 in iter_starts(height, args.tile_size, args.stride):
                for x0 in iter_starts(width, args.tile_size, args.stride):
                    x1 = min(x0 + args.tile_size, width)
                    y1 = min(y0 + args.tile_size, height)
                    box = (x0, y0, x1, y1)
                    if roi_mask is not None and roi_fraction(roi_mask, box) < args.min_roi_fraction:
                        continue
                    tile_name = f"{image_id}_x{x0:05d}_y{y0:05d}_w{x1-x0:04d}_h{y1-y0:04d}.{ext}"
                    out_path = image_out_dir / tile_name
                    tile_file = str(Path("images") / args.split / tile_name).replace("\\", "/")
                    if out_path.exists() and args.existing == "error":
                        raise FileExistsError(
                            f"Tile already exists: {out_path}. Use --existing skip or --existing overwrite."
                        )
                    if not out_path.exists() or args.existing == "overwrite":
                        write_tile(image, out_path, box, ext, args.quality)
                    row = {
                        "tile_file": tile_file,
                        "source_file": str(image_path.resolve()),
                        "x0": x0,
                        "y0": y0,
                        "x1": x1,
                        "y1": y1,
                        "width": x1 - x0,
                        "height": y1 - y0,
                    }
                    rows_by_tile[tile_file] = row
                    rows.append(row)

    with metadata_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["tile_file", "source_file", "x0", "y0", "x1", "y1", "width", "height"],
        )
        writer.writeheader()
        writer.writerows(rows_by_tile[key] for key in sorted(rows_by_tile))
    print(f"processed {len(rows)} tiles; metadata contains {len(rows_by_tile)} tiles")
    print(f"metadata: {metadata_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="Input image files or directories.")
    parser.add_argument("--out-dir", default="data/nodule_coco")
    parser.add_argument("--split", default="train", choices=["train", "val", "test"])
    parser.add_argument("--tile-size", type=int, default=1024)
    parser.add_argument("--stride", type=int, default=768)
    parser.add_argument("--format", default="jpg", choices=["jpg", "png"])
    parser.add_argument(
        "--extensions",
        nargs="+",
        default=list(DEFAULT_IMAGE_SUFFIXES),
        metavar="EXT",
        help="Input extensions to include, without regard to case. Example: --extensions bmp",
    )
    parser.add_argument("--quality", type=int, default=95)
    parser.add_argument(
        "--existing",
        default="skip",
        choices=["error", "skip", "overwrite"],
        help="How to handle an existing tile. Default: skip, preserving LabelMe sidecar files.",
    )
    parser.add_argument("--roi-mask", default=None, help="Optional full-resolution root mask for ROI filtering.")
    parser.add_argument("--min-roi-fraction", type=float, default=0.0)
    return parser.parse_args()


if __name__ == "__main__":
    make_tiles(parse_args())
