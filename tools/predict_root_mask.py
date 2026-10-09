"""Predict root masks with the PaddleSeg model stored in Thirdparty/Paddleseg/root_get."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.phenotyping.paddleseg_root import (  # noqa: E402
    DEFAULT_CONFIG,
    DEFAULT_WEIGHTS,
    PaddleSegRootConfig,
    PaddleSegRootSegmenter,
    write_traits_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="Input root image, e.g. output/Date0810/3_900.bmp")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="PaddleSeg training config yml.",
    )
    parser.add_argument(
        "--weights",
        default=str(DEFAULT_WEIGHTS),
        help="PaddleSeg dynamic-graph weights .pdparams.",
    )
    parser.add_argument("--out-dir", default=str(PROJECT_ROOT / "output" / "root_masks"))
    parser.add_argument("--device", default="gpu", choices=["gpu", "cpu"])
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--foreground-class", type=int, default=1)
    parser.add_argument("--tile-size", type=int, default=None)
    parser.add_argument("--stride", type=int, default=None)
    parser.add_argument("--min-object-size", type=int, default=256)
    parser.add_argument(
        "--skip-traits",
        action="store_true",
        help="Skip skeleton-based trait calculation. Useful for first full-resolution mask checks.",
    )
    parser.add_argument(
        "--skip-overlay",
        action="store_true",
        help="Skip writing the downsampled QC overlay.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    image_path = Path(args.image)
    if not image_path.is_absolute():
        image_path = PROJECT_ROOT / image_path
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = PROJECT_ROOT / out_dir
    stem = image_path.stem

    config = PaddleSegRootConfig.from_yaml(
        config_path=args.config,
        weights_path=args.weights,
        threshold=args.threshold,
        device=args.device,
        foreground_class=args.foreground_class,
        tile_size=args.tile_size,
        stride=args.stride,
        min_object_size=args.min_object_size,
    )
    try:
        segmenter = PaddleSegRootSegmenter(config)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    traits = segmenter.predict_image(
        image_path=image_path,
        output_mask_path=out_dir / f"{stem}_root_mask.png",
        output_clean_mask_path=out_dir / f"{stem}_root_mask_clean.png",
        output_overlay_path=None if args.skip_overlay else out_dir / f"{stem}_root_overlay.jpg",
        output_traits_csv=None if args.skip_traits else out_dir / f"{stem}_root_traits.csv",
        temp_dir=out_dir / "_tmp",
        compute_traits=not args.skip_traits,
    )
    if not args.skip_traits:
        write_traits_json(traits, out_dir / f"{stem}_root_traits.json")
    print(f"root mask: {out_dir / f'{stem}_root_mask.png'}")
    print(f"clean root mask: {out_dir / f'{stem}_root_mask_clean.png'}")
    if not args.skip_overlay:
        print(f"overlay: {out_dir / f'{stem}_root_overlay.jpg'}")
    if not args.skip_traits:
        print(f"traits: {out_dir / f'{stem}_root_traits.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
