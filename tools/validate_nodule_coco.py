"""Validate nodule COCO annotations and print basic dataset statistics."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def validate(args: argparse.Namespace) -> None:
    data_root = Path(args.data_root)
    if not data_root.is_absolute():
        data_root = PROJECT_ROOT / data_root
    ann_path = data_root / "annotations" / f"instances_{args.split}.json"
    with ann_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    categories = {item["id"]: item["name"] for item in data.get("categories", [])}
    if categories != {1: "nodule"}:
        raise SystemExit(f"Unexpected categories: {categories}")

    images = {item["id"]: item for item in data.get("images", [])}
    missing = []
    for item in images.values():
        path = data_root / item["file_name"]
        if not path.exists():
            missing.append(str(path))
    if missing:
        print("Missing images:")
        for path in missing[:20]:
            print(path)
        raise SystemExit(f"{len(missing)} image files are missing.")

    per_image = Counter()
    areas = []
    bad = 0
    for ann in data.get("annotations", []):
        image_id = ann.get("image_id")
        if image_id not in images:
            bad += 1
            continue
        if ann.get("category_id") != 1:
            bad += 1
            continue
        area = float(ann.get("area", 0))
        bbox = ann.get("bbox", [0, 0, 0, 0])
        segmentation = ann.get("segmentation", [])
        if area <= 0 or bbox[2] <= 0 or bbox[3] <= 0 or not segmentation:
            bad += 1
            continue
        per_image[image_id] += 1
        areas.append(area)

    print(f"annotation: {ann_path}")
    print(f"images: {len(images)}")
    print(f"instances: {len(areas)}")
    print(f"images_with_instances: {len(per_image)}")
    print(f"empty_images: {len(images) - len(per_image)}")
    print(f"bad_annotations: {bad}")
    if areas:
        areas_sorted = sorted(areas)
        print(f"area_min: {areas_sorted[0]:.2f}")
        print(f"area_median: {areas_sorted[len(areas_sorted) // 2]:.2f}")
        print(f"area_max: {areas_sorted[-1]:.2f}")
    if bad:
        raise SystemExit("Invalid annotations found.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", default="data/nodule_coco")
    parser.add_argument("--split", default="train", choices=["train", "val", "test"])
    return parser.parse_args()


if __name__ == "__main__":
    validate(parse_args())

