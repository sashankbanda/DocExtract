from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Tuple

MERGE_GAP_RATIO = 0.5
LINE_ALIGNMENT_RATIO = 0.6


def merge_word_bounding_boxes(
    *, word_indexes: Iterable[int], bounding_box_payload: Dict[str, Any]
) -> List[Dict[str, float]]:
    if bounding_box_payload is None:
        raise ValueError("boundingBoxes payload cannot be None.")

    index_lookup = _build_index_lookup(bounding_box_payload)

    unique_indexes: List[int] = []
    seen = set()
    for idx in word_indexes:
        if idx in seen:
            continue
        seen.add(idx)
        unique_indexes.append(int(idx))

    if not unique_indexes:
        raise ValueError("wordIndexes produced no unique indexes to map.")

    selected_boxes: Dict[int, List[Dict[str, float]]] = defaultdict(list)

    for idx in unique_indexes:
        box = index_lookup.get(idx)
        if not box:
            raise ValueError(f"No bounding box found for word index {idx}.")
        selected_boxes[int(box["page"])].append(box)

    merged_results: List[Dict[str, float]] = []
    for page, boxes in selected_boxes.items():
        merged_results.extend(_merge_boxes_for_page(page, boxes))

    return merged_results


def _build_index_lookup(payload: Dict[str, Any]) -> Dict[int, Dict[str, float]]:
    lookup: Dict[int, Dict[str, float]] = {}

    words = payload.get("words")
    if isinstance(words, list):
        for word in words:
            _add_word_to_lookup(lookup, word)

    pages = payload.get("pages")
    if isinstance(pages, list):
        for page in pages:
            for word in page.get("words", []):
                _add_word_to_lookup(lookup, word, default_page=page.get("page", page.get("index")))

    if not lookup:
        raise ValueError("Bounding box payload does not contain recognisable word data.")

    return lookup


def _add_word_to_lookup(
    lookup: Dict[int, Dict[str, float]],
    word_payload: Dict[str, Any],
    default_page: Any = None,
) -> None:
    if not isinstance(word_payload, dict):
        return

    index = word_payload.get("index")
    if index is None:
        return

    bbox = word_payload.get("bbox") or word_payload.get("bounding_box") or {}
    if not bbox:
        return

    page = word_payload.get("page", default_page)
    if page is None:
        return

    x1, y1, x2, y2 = _normalise_box_coordinates(bbox)
    lookup[int(index)] = {
        "page": float(page),
        "x": x1,
        "y": y1,
        "width": x2 - x1,
        "height": y2 - y1,
    }


def _normalise_box_coordinates(bbox: Dict[str, Any]) -> Tuple[float, float, float, float]:
    if {"x", "y", "width", "height"}.issubset(bbox):
        x1 = float(bbox["x"])
        y1 = float(bbox["y"])
        return x1, y1, x1 + float(bbox["width"]), y1 + float(bbox["height"])

    if {"left", "top", "right", "bottom"}.issubset(bbox):
        return (
            float(bbox["left"]),
            float(bbox["top"]),
            float(bbox["right"]),
            float(bbox["bottom"]),
        )

    raise ValueError("Unsupported bounding box coordinate format.")


def _merge_boxes_for_page(page: int, boxes: List[Dict[str, float]]) -> List[Dict[str, float]]:
    if not boxes:
        return []

    sorted_boxes = sorted(boxes, key=lambda b: (b["y"], b["x"]))
    merged: List[Dict[str, float]] = []

    for box in sorted_boxes:
        if not merged:
            merged.append({**box, "page": page})
            continue

        last = merged[-1]
        if _boxes_should_merge(last, box):
            merged[-1] = _merge_two_boxes(last, box)
        else:
            merged.append({**box, "page": page})

    return merged


def _boxes_should_merge(first: Dict[str, float], second: Dict[str, float]) -> bool:
    same_page = int(first["page"]) == int(second["page"])
    if not same_page:
        return False

    vertical_overlap = abs(first["y"] - second["y"]) <= max(first["height"], second["height"]) * LINE_ALIGNMENT_RATIO
    horizontal_gap = second["x"] - (first["x"] + first["width"])

    return vertical_overlap and horizontal_gap <= max(first["width"], second["width"]) * MERGE_GAP_RATIO


def _merge_two_boxes(first: Dict[str, float], second: Dict[str, float]) -> Dict[str, float]:
    x1 = min(first["x"], second["x"])
    y1 = min(first["y"], second["y"])
    x2 = max(first["x"] + first["width"], second["x"] + second["width"])
    y2 = max(first["y"] + first["height"], second["y"] + second["height"])

    return {
        "page": first["page"],
        "x": x1,
        "y": y1,
        "width": x2 - x1,
        "height": y2 - y1,
    }
