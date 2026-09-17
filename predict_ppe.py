"""Run the SH17 YOLOv9-e PPE detector on images, videos, streams, or webcams."""

from __future__ import annotations

import argparse
from pathlib import Path

from ultralytics import YOLO


DEFAULT_MODEL = "SH17_YOLOv9e_PPE_17class.pt"


def parse_source(value: str):
    """Convert a numeric source such as '0' into a webcam index."""
    return int(value) if value.isdigit() else value


def main() -> None:
    parser = argparse.ArgumentParser(description="Industrial PPE detection using SH17 YOLOv9-e")
    parser.add_argument("--source", required=True, help="Image/video/folder/URL/RTSP stream or webcam index")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Path to the downloaded .pt checkpoint")
    parser.add_argument("--conf", type=float, default=0.25, help="Minimum confidence threshold")
    parser.add_argument("--iou", type=float, default=0.50, help="NMS IoU threshold")
    parser.add_argument("--imgsz", type=int, default=1280, help="Inference image size")
    parser.add_argument("--device", default=None, help="Examples: 0 or cpu; omitted means automatic selection")
    parser.add_argument("--show", action="store_true", help="Display annotated output")
    parser.add_argument("--save-txt", action="store_true", help="Save YOLO-format labels")
    args = parser.parse_args()

    model_path = Path(args.model)
    if not model_path.exists():
        raise FileNotFoundError(
            f"Model not found: {model_path.resolve()}\n"
            "Download it from the GitHub Release link in README.md."
        )

    model = YOLO(str(model_path))
    model.predict(
        source=parse_source(args.source),
        conf=args.conf,
        iou=args.iou,
        imgsz=args.imgsz,
        device=args.device,
        show=args.show,
        save=True,
        save_txt=args.save_txt,
        project="runs/ppe",
        name="predict",
    )


if __name__ == "__main__":
    main()

