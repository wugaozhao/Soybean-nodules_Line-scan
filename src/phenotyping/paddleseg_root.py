"""PaddleSeg adapter for tiled soybean root segmentation."""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import yaml
from PIL import Image

from .root_traits import clean_root_mask, measure_root_traits
from .tiling import Tile, iter_tiles


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "Thirdparty/Paddleseg/root_get/segformer_cotton_root_1024x1024_150k.yml"
DEFAULT_WEIGHTS = PROJECT_ROOT / "Thirdparty/Paddleseg/root_get/model.pdparams"
LOCAL_PADDLESEG_SOURCE = PROJECT_ROOT / "Thirdparty/Paddleseg/PaddleSeg-release-2.10"
SEGFORMER_VARIANTS = {
    "SegFormer_B0": ("MixVisionTransformer_B0", 256),
    "SegFormer_B1": ("MixVisionTransformer_B1", 256),
    "SegFormer_B2": ("MixVisionTransformer_B2", 768),
    "SegFormer_B3": ("MixVisionTransformer_B3", 768),
    "SegFormer_B4": ("MixVisionTransformer_B4", 768),
    "SegFormer_B5": ("MixVisionTransformer_B5", 768),
}


@dataclass(frozen=True)
class PaddleSegRootConfig:
    config_path: Path
    weights_path: Path
    tile_size: int = 512
    stride: int = 400
    threshold: float = 0.5
    foreground_class: int = 1
    mean: tuple[float, float, float] = (0.5, 0.5, 0.5)
    std: tuple[float, float, float] = (0.5, 0.5, 0.5)
    min_object_size: int = 256
    device: str = "gpu"

    @classmethod
    def from_yaml(
        cls,
        config_path: str | os.PathLike[str],
        weights_path: str | os.PathLike[str],
        threshold: float = 0.5,
        device: str = "gpu",
        foreground_class: int = 1,
        tile_size: int | None = None,
        stride: int | None = None,
        min_object_size: int = 256,
    ) -> "PaddleSegRootConfig":
        config_path = Path(config_path)
        with config_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        test_config = raw.get("test_config", {}) or {}
        crop = test_config.get("crop_size") or [512, 512]
        stride_cfg = test_config.get("stride") or [400, 400]
        if crop[0] != crop[1]:
            raise ValueError(f"Only square crop_size is currently supported, got {crop}")
        if stride_cfg[0] != stride_cfg[1]:
            raise ValueError(f"Only square stride is currently supported, got {stride_cfg}")

        mean, std = _normalize_stats_from_config(raw)
        return cls(
            config_path=config_path,
            weights_path=Path(weights_path),
            tile_size=int(tile_size or crop[0]),
            stride=int(stride or stride_cfg[0]),
            threshold=threshold,
            foreground_class=foreground_class,
            mean=mean,
            std=std,
            min_object_size=min_object_size,
            device=device,
        )


def _normalize_stats_from_config(raw: dict) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    transforms = (raw.get("val_dataset") or {}).get("transforms") or []
    for transform in transforms:
        if not isinstance(transform, dict) or transform.get("type") != "Normalize":
            continue
        mean = tuple(float(v) for v in transform.get("mean", [0.5, 0.5, 0.5]))
        std = tuple(float(v) for v in transform.get("std", [0.5, 0.5, 0.5]))
        if len(mean) != 3 or len(std) != 3:
            raise ValueError(f"Normalize mean/std must have three values, got {mean}/{std}")
        return mean, std
    return (0.5, 0.5, 0.5), (0.5, 0.5, 0.5)


def _write_runtime_config_without_pretrained(config_path: Path) -> Path:
    """Create a temporary inference config that skips URL pretrained weights."""
    with config_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    raw = _normalize_model_config_for_paddleseg_210(raw)

    fd, temp_path = tempfile.mkstemp(prefix="paddleseg_root_infer_", suffix=".yml")
    os.close(fd)
    path = Path(temp_path)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(raw, fh, allow_unicode=True, sort_keys=False)
    return path


def _normalize_model_config_for_paddleseg_210(raw: dict) -> dict:
    """Normalize project training configs to the PaddleSeg 2.10 model schema."""
    normalized = dict(raw)
    model = dict(normalized.get("model") or {})
    model_type = model.get("type")

    if model_type in SEGFORMER_VARIANTS:
        backbone_type, embedding_dim = SEGFORMER_VARIANTS[model_type]
        model = {
            "type": "SegFormer",
            "backbone": {
                "type": backbone_type,
                "pretrained": None,
            },
            "embedding_dim": model.get("embedding_dim", embedding_dim),
            "num_classes": model.get("num_classes", 2),
        }
    elif model:
        model["pretrained"] = None
        if isinstance(model.get("backbone"), dict):
            model["backbone"] = dict(model["backbone"])
            model["backbone"]["pretrained"] = None

    normalized["model"] = model
    return normalized


class PaddleSegRootSegmenter:
    """Load a PaddleSeg dynamic-graph model and run tiled root segmentation."""

    def __init__(self, config: PaddleSegRootConfig):
        self.config = config
        self._load_model()

    def _load_model(self) -> None:
        if LOCAL_PADDLESEG_SOURCE.exists():
            sys.path.insert(0, str(LOCAL_PADDLESEG_SOURCE))

        try:
            import paddle
            from paddleseg.cvlibs import Config, SegBuilder
            from paddleseg.utils import utils
        except ImportError as exc:
            raise RuntimeError(
                "PaddleSeg root segmentation requires paddlepaddle and PaddleSeg runtime dependencies. "
                "This project includes a local PaddleSeg source copy under "
                f"{LOCAL_PADDLESEG_SOURCE}. Install the remaining runtime packages first."
            ) from exc

        self.paddle = paddle
        if self.config.device:
            paddle.set_device(self.config.device)

        runtime_config_path = _write_runtime_config_without_pretrained(self.config.config_path)
        try:
            cfg = Config(str(runtime_config_path))
            builder = SegBuilder(cfg)
            model = builder.model
            utils.load_entire_model(model, str(self.config.weights_path))
            model.eval()
            self.model = model
        finally:
            try:
                runtime_config_path.unlink()
            except OSError:
                pass

    def predict_tile_probability(self, tile_rgb: np.ndarray) -> np.ndarray:
        """Predict foreground probability for one RGB tile."""
        original_h, original_w = tile_rgb.shape[:2]
        padded = _pad_to_size(tile_rgb, self.config.tile_size)
        image = padded.astype("float32") / 255.0
        image = (image - np.array(self.config.mean, dtype=np.float32)) / np.array(
            self.config.std,
            dtype=np.float32,
        )
        image = np.transpose(image, (2, 0, 1))[None, :, :, :]

        with self.paddle.no_grad():
            tensor = self.paddle.to_tensor(image)
            logits = self.model(tensor)
            if isinstance(logits, (list, tuple)):
                logits = logits[0]
            if tuple(logits.shape[-2:]) != tuple(padded.shape[:2]):
                logits = self.paddle.nn.functional.interpolate(
                    logits,
                    size=padded.shape[:2],
                    mode="bilinear",
                    align_corners=False,
                )
            prob = self.paddle.nn.functional.softmax(logits, axis=1)[
                0,
                self.config.foreground_class,
            ].numpy()
        return prob[:original_h, :original_w]

    def predict_image(
        self,
        image_path: str | os.PathLike[str],
        output_mask_path: str | os.PathLike[str],
        output_clean_mask_path: str | os.PathLike[str] | None = None,
        output_overlay_path: str | os.PathLike[str] | None = None,
        output_traits_csv: str | os.PathLike[str] | None = None,
        temp_dir: str | os.PathLike[str] | None = None,
        compute_traits: bool = True,
    ) -> dict[str, float | int | str]:
        """Run tiled prediction on a large image and write mask/traits outputs."""
        Image.MAX_IMAGE_PIXELS = None
        image_path = Path(image_path)
        output_mask_path = Path(output_mask_path)
        output_mask_path.parent.mkdir(parents=True, exist_ok=True)
        if temp_dir is None:
            temp_dir = output_mask_path.parent / "_tmp"
        temp_dir = Path(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)

        with Image.open(image_path) as img:
            img = img.convert("RGB")
            width, height = img.size
            prob_sum_path = temp_dir / f"{image_path.stem}_root_prob_sum.uint16.memmap"
            count_path = temp_dir / f"{image_path.stem}_root_count.uint16.memmap"
            prob_sum = np.memmap(prob_sum_path, dtype=np.uint16, mode="w+", shape=(height, width))
            counts = np.memmap(count_path, dtype=np.uint16, mode="w+", shape=(height, width))
            prob_sum[:] = 0
            counts[:] = 0

            tiles = list(iter_tiles(width, height, self.config.tile_size, self.config.stride))
            for index, tile in enumerate(tiles, start=1):
                tile_rgb = np.asarray(img.crop((tile.x0, tile.y0, tile.x1, tile.y1)))
                prob = self.predict_tile_probability(tile_rgb)
                prob_u8 = np.clip(np.rint(prob * 255.0), 0, 255).astype(np.uint16)
                _accumulate_tile(prob_sum, counts, tile, prob_u8)
                if index % 50 == 0 or index == len(tiles):
                    print(f"root tiles: {index}/{len(tiles)}")

        mask = np.empty((height, width), dtype=np.uint8)
        threshold_u8 = self.config.threshold * 255.0
        block_rows = 512
        for y0 in range(0, height, block_rows):
            y1 = min(y0 + block_rows, height)
            block_counts = np.maximum(counts[y0:y1], 1)
            mask[y0:y1] = ((prob_sum[y0:y1] / block_counts) >= threshold_u8).astype(np.uint8) * 255
        Image.fromarray(mask, mode="L").save(output_mask_path)

        clean_mask_path = output_clean_mask_path or output_mask_path.with_name(
            f"{output_mask_path.stem}_clean{output_mask_path.suffix}"
        )
        clean_mask_path = Path(clean_mask_path)
        cleaned = clean_root_mask(mask, min_object_size=self.config.min_object_size)
        Image.fromarray(cleaned, mode="L").save(clean_mask_path)

        traits = measure_root_traits(cleaned, min_object_size=0).to_dict() if compute_traits else {}
        traits.update(
            {
                "image_path": str(image_path),
                "mask_path": str(output_mask_path),
                "clean_mask_path": str(clean_mask_path),
                "image_width": width,
                "image_height": height,
                "tile_size": self.config.tile_size,
                "stride": self.config.stride,
                "threshold": self.config.threshold,
            }
        )

        if output_overlay_path:
            write_overlay(image_path, cleaned, output_overlay_path)
            traits["overlay_path"] = str(output_overlay_path)

        if output_traits_csv and traits:
            write_traits_csv(traits, output_traits_csv)

        return traits


def _pad_to_size(tile_rgb: np.ndarray, size: int) -> np.ndarray:
    h, w = tile_rgb.shape[:2]
    if h == size and w == size:
        return tile_rgb
    padded = np.zeros((size, size, 3), dtype=tile_rgb.dtype)
    padded[:h, :w] = tile_rgb
    return padded


def _accumulate_tile(
    prob_sum: np.memmap,
    counts: np.memmap,
    tile: Tile,
    prob_u8: np.ndarray,
) -> None:
    region = np.s_[tile.y0 : tile.y1, tile.x0 : tile.x1]
    prob_sum[region] += prob_u8[: tile.height, : tile.width]
    counts[region] += 1


def write_overlay(
    image_path: str | os.PathLike[str],
    mask: np.ndarray,
    output_overlay_path: str | os.PathLike[str],
    max_size: int = 2400,
) -> None:
    """Write a downsampled QC overlay so huge inputs remain easy to inspect."""
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        scale = min(max_size / img.width, max_size / img.height, 1.0)
        preview_size = (int(img.width * scale), int(img.height * scale))
        img = img.resize(preview_size, Image.Resampling.LANCZOS)
    small_mask = np.asarray(
        Image.fromarray(mask, mode="L").resize(preview_size, Image.Resampling.NEAREST)
    )
    rgb = np.asarray(img).copy()
    overlay = rgb.copy()
    overlay[small_mask > 0] = (255, 64, 64)
    blended = np.clip(rgb.astype(np.float32) * 0.65 + overlay.astype(np.float32) * 0.35, 0, 255).astype(
        np.uint8
    )
    output_overlay_path = Path(output_overlay_path)
    output_overlay_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(blended, mode="RGB").save(output_overlay_path)


def write_traits_csv(traits: dict[str, float | int | str], csv_path: str | os.PathLike[str]) -> None:
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(traits.keys()))
        writer.writeheader()
        writer.writerow(traits)


def write_traits_json(traits: dict[str, float | int | str], json_path: str | os.PathLike[str]) -> None:
    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(traits, fh, ensure_ascii=False, indent=2)
