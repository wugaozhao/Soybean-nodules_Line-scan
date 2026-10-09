"""Convert labelme polygon annotations to COCO instance-segmentation JSON."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def polygon_area(points: list[float]) -> float:
    coords = list(zip(points[0::2], points[1::2]))
    if len(coords) < 3:
        return 0.0
    acc = 0.0
    for i, (x0, y0) in enumerate(coords):
        x1, y1 = coords[(i + 1) % len(coords)]
        acc += x0 * y1 - x1 * y0
    return abs(acc) / 2.0


def polygon_bbox(points: list[float]) -> list[float]:
    xs = points[0::2]
    ys = points[1::2]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    return [x0, y0, x1 - x0, y1 - y0]


def rectangle_to_polygon(points: list[list[float]]) -> list[list[float]]:
    (x0, y0), (x1, y1) = points[:2]
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def circle_to_polygon(points: list[list[float]], vertices: int = 24) -> list[list[float]]:
    (cx, cy), (px, py) = points[:2]
    radius = math.hypot(px - cx, py - cy)
    return [
        [cx + radius * math.cos(2 * math.pi * i / vertices), cy + radius * math.sin(2 * math.pi * i / vertices)]
        for i in range(vertices)
    ]


def shape_points(shape: dict) -> list[float] | None:
    label = str(shape.get("label", "")).strip().lower()
    if label != "nodule":
        return None
    raw_points = shape.get("points") or []
    shape_type = shape.get("shape_type", "polygon")
    if shape_type == "rectangle":
        raw_points = rectangle_to_polygon(raw_points)
    elif shape_type == "circle":
        raw_points = circle_to_polygon(raw_points)
    if len(raw_points) < 3:
        return None
    return [float(value) for point in raw_points for value in point[:2]]


def image_size(image_path: Path, data: dict) -> tuple[int, int]:
    width = data.get("imageWidth")
    height = data.get("imageHeight")
    if width and height:
        return int(width), int(height)
    with Image.open(image_path) as img:
        return img.size


def convert_split(args: argparse.Namespace) -> None:
    data_root = Path(args.data_root)
    if not data_root.is_absolute():
        data_root = PROJECT_ROOT / data_root
    image_dir = data_root / "images" / args.split
    ann_dir = data_root / "annotations"
    ann_dir.mkdir(parents=True, exist_ok=True)

    images = []
    annotations = []
    ann_id = 1
    img_id = 1
    for json_path in sorted(image_dir.glob("*.json")):
        with json_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        image_name = data.get("imagePath") or f"{json_path.stem}.jpg"
        image_path = image_dir / image_name
        if not image_path.exists():
            candidates = list(image_dir.glob(f"{json_path.stem}.*"))
            candidates = [p for p in candidates if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]
            if not candidates:
                print(f"skip {json_path}: image not found")
                continue
            image_path = candidates[0]

        width, height = image_size(image_path, data)
        file_name = str(Path("images") / args.split / image_path.name).replace("\\", "/")
        images.append({"id": img_id, "file_name": file_name, "width": width, "height": height})

        for shape in data.get("shapes", []):
            points = shape_points(shape)
            if points is None:
                continue
            area = polygon_area(points)
            if area < args.min_area:
                continue
            annotations.append(
                {
                    "id": ann_id,
                    "image_id": img_id,
                    "category_id": 1,
                    "segmentation": [points],
                    "area": area,
                    "bbox": polygon_bbox(points),
                    "iscrowd": 0,
                }
            )
            ann_id += 1
        img_id += 1

    coco = {
        "images": images,
        "annotations": annotations,
        "categories": [{"id": 1, "name": "nodule", "supercategory": "root"}],
    }
    out_path = ann_dir / f"instances_{args.split}.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(coco, fh, ensure_ascii=False)
    print(f"images: {len(images)}")
    print(f"annotations: {len(annotations)}")
    print(f"coco: {out_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", default="data/nodule_coco")
    parser.add_argument("--split", default="train", choices=["train", "val", "test"])
    parser.add_argument("--min-area", type=float, default=4.0)
    return parser.parse_args()


if __name__ == "__main__":
    convert_split(parse_args())
