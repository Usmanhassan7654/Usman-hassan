"""Run reproducible PPE inference tests and save annotated videos, frames and JSON."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path

import cv2
from ultralytics import YOLO


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test SH17 PPE detection on one or more videos")
    parser.add_argument("sources", nargs="+", help="Input video paths")
    parser.add_argument("--model", default="SH17_YOLOv9e_PPE_17class.pt")
    parser.add_argument("--output", default="test_results")
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--iou", type=float, default=0.50)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default="cpu")
    return parser.parse_args()


def make_h264(source: Path, destination: Path) -> bool:
    """Convert OpenCV's temporary MP4 to a browser-friendly H.264 MP4 when FFmpeg exists."""
    if not shutil.which("ffmpeg"):
        source.replace(destination)
        return False
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
            "-movflags", "+faststart", "-pix_fmt", "yuv420p", str(destination),
        ],
        check=True,
    )
    source.unlink()
    return True


def test_video(model: YOLO, source: Path, output_dir: Path, args: argparse.Namespace) -> dict:
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {source}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 10.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    stem = source.stem
    temporary_video = output_dir / f".{stem}_annotated.mp4"
    annotated_video = output_dir / f"{stem}_annotated.mp4"
    representative_frame = output_dir / f"{stem}_best_frame.jpg"
    writer = cv2.VideoWriter(
        str(temporary_video), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    if not writer.isOpened():
        raise RuntimeError(f"Could not create video: {temporary_video}")

    counts: Counter[str] = Counter()
    frames_with_detections = 0
    frame_count = 0
    best_score = -1.0
    best_frame = None
    started = time.perf_counter()

    while True:
        ok, frame = capture.read()
        if not ok:
            break
        result = model.predict(
            frame,
            conf=args.conf,
            iou=args.iou,
            imgsz=args.imgsz,
            device=args.device,
            verbose=False,
        )[0]
        annotated = result.plot()
        writer.write(annotated)
        frame_count += 1

        score = 0.0
        if result.boxes is not None and len(result.boxes):
            frames_with_detections += 1
            class_ids = result.boxes.cls.int().cpu().tolist()
            confidences = result.boxes.conf.cpu().tolist()
            for class_id in class_ids:
                counts[model.names[class_id]] += 1
            score = float(sum(confidences))
        if score > best_score:
            best_score = score
            best_frame = annotated.copy()

    elapsed = time.perf_counter() - started
    capture.release()
    writer.release()
    if best_frame is not None:
        cv2.imwrite(str(representative_frame), best_frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
    h264 = make_h264(temporary_video, annotated_video)

    return {
        "source_file": source.name,
        "annotated_video": annotated_video.name,
        "representative_frame": representative_frame.name,
        "frames_processed": frame_count,
        "frames_with_detections": frames_with_detections,
        "duration_seconds": round(frame_count / fps, 3),
        "processing_seconds": round(elapsed, 3),
        "processing_fps": round(frame_count / elapsed, 3) if elapsed else None,
        "detections_by_class": dict(sorted(counts.items())),
        "h264_output": h264,
    }


def main() -> None:
    args = parse_args()
    model_path = Path(args.model)
    if not model_path.is_file():
        raise FileNotFoundError(f"Model not found: {model_path}")
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    model = YOLO(str(model_path))
    results = [test_video(model, Path(item), output_dir, args) for item in args.sources]
    summary = {
        "model": model_path.name,
        "model_classes": model.names,
        "settings": {
            "confidence": args.conf,
            "iou": args.iou,
            "image_size": args.imgsz,
            "device": args.device,
        },
        "videos": results,
    }
    summary_path = output_dir / "results_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
