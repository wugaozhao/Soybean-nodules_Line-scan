"""Root-mask post-processing and basic phenotype extraction."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage as ndi
from skimage.measure import label, regionprops
from skimage.morphology import binary_closing, remove_small_objects, skeletonize


@dataclass(frozen=True)
class RootTraits:
    root_area_px: int
    root_length_px: float
    component_count: int
    largest_component_area_px: int
    branch_point_count: int
    endpoint_count: int

    def to_dict(self) -> dict[str, float | int]:
        return {
            "root_area_px": self.root_area_px,
            "root_length_px": self.root_length_px,
            "component_count": self.component_count,
            "largest_component_area_px": self.largest_component_area_px,
            "branch_point_count": self.branch_point_count,
            "endpoint_count": self.endpoint_count,
        }


def clean_root_mask(mask: np.ndarray, min_object_size: int = 256) -> np.ndarray:
    """Return a cleaned binary root mask as uint8 values 0/255."""
    binary = mask > 0
    if min_object_size > 0:
        binary = remove_small_objects(binary, min_size=min_object_size)
    binary = binary_closing(binary, footprint=np.ones((3, 3), dtype=bool))
    return (binary.astype(np.uint8) * 255)


def skeleton_length_px(skeleton: np.ndarray) -> float:
    """Estimate skeleton length using 8-neighborhood edge weights."""
    skel = skeleton.astype(bool)
    horizontal = np.logical_and(skel[:, 1:], skel[:, :-1]).sum()
    vertical = np.logical_and(skel[1:, :], skel[:-1, :]).sum()
    diag_1 = np.logical_and(skel[1:, 1:], skel[:-1, :-1]).sum()
    diag_2 = np.logical_and(skel[1:, :-1], skel[:-1, 1:]).sum()
    return float(horizontal + vertical + (diag_1 + diag_2) * np.sqrt(2.0))


def skeleton_node_counts(skeleton: np.ndarray) -> tuple[int, int]:
    """Return branch point and endpoint counts from an 8-neighborhood skeleton."""
    skel = skeleton.astype(np.uint8)
    kernel = np.array(
        [[1, 1, 1], [1, 0, 1], [1, 1, 1]],
        dtype=np.uint8,
    )
    neighbors = ndi.convolve(skel, kernel, mode="constant", cval=0)
    endpoint_count = int(np.logical_and(skel == 1, neighbors == 1).sum())
    branch_point_count = int(np.logical_and(skel == 1, neighbors >= 3).sum())
    return branch_point_count, endpoint_count


def measure_root_traits(mask: np.ndarray, min_object_size: int = 256) -> RootTraits:
    """Measure basic traits from a binary root mask."""
    cleaned = clean_root_mask(mask, min_object_size=min_object_size)
    binary = cleaned > 0
    labels = label(binary, connectivity=2)
    props = regionprops(labels)
    component_count = len(props)
    largest_area = int(max((prop.area for prop in props), default=0))
    skel = skeletonize(binary)
    branch_points, endpoints = skeleton_node_counts(skel)
    return RootTraits(
        root_area_px=int(binary.sum()),
        root_length_px=skeleton_length_px(skel),
        component_count=component_count,
        largest_component_area_px=largest_area,
        branch_point_count=branch_points,
        endpoint_count=endpoints,
    )
