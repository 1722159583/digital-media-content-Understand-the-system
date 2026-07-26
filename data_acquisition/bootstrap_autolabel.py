"""Train a 20-image bootstrap detector and create reviewable auto-labels."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from PIL import Image
from ultralytics import YOLO


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ACQUISITION_DIR = PROJECT_ROOT / "data_acquisition"
MANIFEST_PATH = ACQUISITION_DIR / "bootstrap_seed_manifest.json"
DATASET_DIR = ACQUISITION_DIR / "yolo_dataset"
DATA_YAML = DATASET_DIR / "data.yaml"
RUNS_DIR = ACQUISITION_DIR / "runs"
RUN_NAME = "bootstrap20"
AUTO_LABEL_DIR = ACQUISITION_DIR / "annotations" / "auto_anylabeling"
REVIEW_CSV = AUTO_LABEL_DIR / "review_manifest.csv"
DEFAULT_BASE_MODEL = PROJECT_ROOT / "models" / "yolo11n.pt"
DEFAULT_BEST_MODEL = RUNS_DIR / RUN_NAME / "weights" / "best.pt"
EXPORTED_MODEL = PROJECT_ROOT / "models" / "game_highlight_bootstrap20.pt"


class BootstrapError(RuntimeError):
    """Raised when the bootstrap training workflow cannot continue."""


def load_manifest() -> dict[str, Any]:
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BootstrapError(f"cannot read seed manifest: {exc}") from exc

    class_names = manifest.get("class_names")
    images = manifest.get("images")
    if class_names != ["penta_kill", "multi_kill", "kill_feed"]:
        raise BootstrapError("seed manifest class order does not match classes.txt")
    if not isinstance(images, list) or len(images) != 20:
        raise BootstrapError("seed manifest must contain exactly 20 images")
    return manifest


def validate_box(box: dict[str, Any], class_names: list[str]) -> None:
    if box.get("class_name") not in class_names:
        raise BootstrapError(f"unknown class in seed box: {box.get('class_name')}")
    coordinates = box.get("xyxy")
    if not isinstance(coordinates, list) or len(coordinates) != 4:
        raise BootstrapError("every seed box must use normalized xyxy coordinates")
    x1, y1, x2, y2 = (float(value) for value in coordinates)
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        raise BootstrapError(f"invalid normalized box: {coordinates}")


def yolo_line(class_id: int, xyxy: list[float]) -> str:
    x1, y1, x2, y2 = xyxy
    return (
        f"{class_id} {(x1 + x2) / 2:.6f} {(y1 + y2) / 2:.6f} "
        f"{x2 - x1:.6f} {y2 - y1:.6f}"
    )


def anylabeling_document(
    image_path: Path,
    boxes: list[dict[str, Any]],
    class_names: list[str],
    scores: list[float] | None = None,
) -> dict[str, Any]:
    with Image.open(image_path) as image:
        width, height = image.size

    shapes = []
    for index, box in enumerate(boxes):
        validate_box(box, class_names)
        x1, y1, x2, y2 = box["xyxy"]
        shape = {
            "label": box["class_name"],
            "points": [[x1 * width, y1 * height], [x2 * width, y2 * height]],
            "group_id": None,
            "description": "",
            "difficult": False,
            "shape_type": "rectangle",
            "flags": {},
            "attributes": {},
        }
        if scores is not None:
            shape["score"] = round(scores[index], 6)
        shapes.append(shape)

    return {
        "version": "2.5.4",
        "flags": {},
        "shapes": shapes,
        "imagePath": str(image_path),
        "imageData": None,
        "imageHeight": height,
        "imageWidth": width,
    }


def prepare_seed_dataset(manifest: dict[str, Any]) -> None:
    class_names = manifest["class_names"]
    class_ids = {name: index for index, name in enumerate(class_names)}
    split_counts = {"train": 0, "val": 0}

    for item in manifest["images"]:
        split = item.get("split")
        if split not in split_counts:
            raise BootstrapError(f"seed image has invalid split: {split}")
        source = PROJECT_ROOT / item["path"]
        if not source.is_file():
            raise BootstrapError(f"seed image is missing: {source}")
        boxes = item.get("boxes", [])
        for box in boxes:
            validate_box(box, class_names)

        image_destination = DATASET_DIR / "images" / split / source.name
        label_destination = DATASET_DIR / "labels" / split / f"{source.stem}.txt"
        image_destination.parent.mkdir(parents=True, exist_ok=True)
        label_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, image_destination)
        lines = [
            yolo_line(class_ids[box["class_name"]], box["xyxy"]) for box in boxes
        ]
        label_destination.write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="ascii"
        )

        game_type = source.parent.name
        json_destination = (
            ACQUISITION_DIR
            / "annotations"
            / "anylabeling"
            / game_type
            / f"{source.stem}.json"
        )
        json_destination.parent.mkdir(parents=True, exist_ok=True)
        document = anylabeling_document(source, boxes, class_names)
        json_destination.write_text(
            json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        split_counts[split] += 1

    print(
        f"[info] prepared seed dataset: train={split_counts['train']}, "
        f"val={split_counts['val']}"
    )


def train_model(args: argparse.Namespace) -> Path:
    if not args.base_model.is_file():
        raise BootstrapError(f"base model is missing: {args.base_model}")
    model = YOLO(str(args.base_model))
    model.train(
        data=str(DATA_YAML),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        workers=0,
        patience=max(5, args.epochs // 3),
        seed=42,
        deterministic=True,
        pretrained=True,
        project=str(RUNS_DIR),
        name=RUN_NAME,
        exist_ok=True,
        plots=True,
        verbose=True,
    )
    if not DEFAULT_BEST_MODEL.is_file():
        raise BootstrapError(f"training did not produce {DEFAULT_BEST_MODEL}")
    shutil.copy2(DEFAULT_BEST_MODEL, EXPORTED_MODEL)
    print(f"[info] exported bootstrap model: {EXPORTED_MODEL}")
    return EXPORTED_MODEL


def result_boxes(result: Any, class_names: list[str]) -> tuple[list[dict[str, Any]], list[float]]:
    boxes: list[dict[str, Any]] = []
    scores: list[float] = []
    if result.boxes is None:
        return boxes, scores
    height, width = result.orig_shape
    for xyxy_tensor, class_tensor, confidence_tensor in zip(
        result.boxes.xyxy, result.boxes.cls, result.boxes.conf
    ):
        x1, y1, x2, y2 = (float(value) for value in xyxy_tensor.tolist())
        class_id = int(class_tensor.item())
        boxes.append(
            {
                "class_name": class_names[class_id],
                "xyxy": [x1 / width, y1 / height, x2 / width, y2 / height],
            }
        )
        scores.append(float(confidence_tensor.item()))
    return boxes, scores


def auto_label_remaining(
    manifest: dict[str, Any], weights: Path, args: argparse.Namespace
) -> None:
    if not weights.is_file():
        raise BootstrapError(f"trained weights are missing: {weights}")
    seed_paths = {(PROJECT_ROOT / item["path"]).resolve() for item in manifest["images"]}
    candidates = sorted(
        path
        for game_type in ("lol", "csgo")
        for path in (ACQUISITION_DIR / "raw_images" / game_type).glob("*.jpg")
        if path.resolve() not in seed_paths
    )
    if not candidates:
        raise BootstrapError("no non-seed images are available for auto-labeling")

    model = YOLO(str(weights))
    results = model.predict(
        source=[str(path) for path in candidates],
        stream=True,
        conf=args.confidence,
        iou=0.5,
        max_det=args.max_det,
        imgsz=args.imgsz,
        device=args.device,
        verbose=False,
    )
    review_rows: list[dict[str, str | int | float]] = []
    for source_path, result in zip(candidates, results, strict=True):
        image_path = source_path.resolve()
        game_type = image_path.parent.name
        boxes, scores = result_boxes(result, manifest["class_names"])
        output = AUTO_LABEL_DIR / game_type / f"{image_path.stem}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        document = anylabeling_document(
            image_path, boxes, manifest["class_names"], scores
        )
        output.write_text(
            json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        review_rows.append(
            {
                "image_id": image_path.stem,
                "game_type": game_type.upper(),
                "image_path": image_path.relative_to(PROJECT_ROOT).as_posix(),
                "annotation_path": output.relative_to(PROJECT_ROOT).as_posix(),
                "prediction_count": len(boxes),
                "max_confidence": round(max(scores, default=0.0), 6),
                "review_status": "pending_review",
                "reviewer": "",
                "notes": "",
            }
        )

    AUTO_LABEL_DIR.mkdir(parents=True, exist_ok=True)
    with REVIEW_CSV.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(review_rows[0]))
        writer.writeheader()
        writer.writerows(review_rows)
    detected = sum(int(row["prediction_count"]) > 0 for row in review_rows)
    print(
        f"[info] generated {len(review_rows)} candidate JSON files; "
        f"{detected} contain predictions; review list: {REVIEW_CSV}"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("prepare", "train", "predict", "all"), nargs="?", default="all"
    )
    parser.add_argument("--base-model", type=Path, default=DEFAULT_BASE_MODEL)
    parser.add_argument("--weights", type=Path, default=DEFAULT_BEST_MODEL)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--imgsz", type=int, default=512)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--confidence", type=float, default=0.15)
    parser.add_argument("--max-det", type=int, default=20)
    args = parser.parse_args(argv)
    if args.epochs < 1 or args.imgsz < 320 or args.batch < 1:
        parser.error("epochs, imgsz, and batch must be positive; imgsz >= 320")
    if not 0 < args.confidence < 1:
        parser.error("--confidence must be between 0 and 1")
    if not 1 <= args.max_det <= 300:
        parser.error("--max-det must be between 1 and 300")
    args.base_model = args.base_model.resolve()
    args.weights = args.weights.resolve()
    return args


def run(args: argparse.Namespace) -> int:
    manifest = load_manifest()
    if args.command in {"prepare", "all"}:
        prepare_seed_dataset(manifest)
    if args.command in {"train", "all"}:
        args.weights = train_model(args)
    if args.command in {"predict", "all"}:
        auto_label_remaining(manifest, args.weights, args)
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(parse_args(argv))
    except (BootstrapError, OSError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
