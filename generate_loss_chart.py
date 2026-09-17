"""Generate the loss chart by safely parsing non-executable pickle opcodes.

This utility does not unpickle or execute the checkpoint. It reads the numeric
training history stored in the PyTorch ZIP container and plots the six losses.
"""

from __future__ import annotations

import pickletools
import zipfile
from pathlib import Path

MODEL = Path("SH17_YOLOv9e_PPE_17class.pt")
OUTPUT = Path("assets/sh17_yolo9e_loss_chart.svg")


def extract_training_results(model_path: Path) -> dict[str, list[float]]:
    with zipfile.ZipFile(model_path) as archive:
        pickle_name = next(name for name in archive.namelist() if name.endswith("/data.pkl"))
        operations = list(pickletools.genops(archive.read(pickle_name)))

    start = next(index for index, (_, arg, _) in enumerate(operations) if arg == "train_results")
    results: dict[str, list[float]] = {}
    index = start + 5

    while index < len(operations):
        operation, argument, _ = operations[index]
        if operation.name == "SETITEMS":
            break
        if operation.name != "BINUNICODE":
            index += 1
            continue

        key = argument
        index += 1
        while operations[index][0].name != "MARK":
            index += 1
        index += 1

        values: list[float] = []
        while operations[index][0].name not in ("APPENDS", "SETITEMS"):
            value_operation, value, _ = operations[index]
            if value_operation.name in ("BINFLOAT", "BININT", "BININT1", "BININT2", "LONG1", "LONG4"):
                values.append(value)
            index += 1

        if operations[index][0].name == "APPENDS":
            index += 1
        results[key] = values

    return results


def main() -> None:
    history = extract_training_results(MODEL)
    epochs = history["epoch"]

    width, height = 1400, 650
    top, bottom = 120, 560
    panel_width = 570
    panel_lefts = (90, 760)
    y_min, y_max = 0.25, 1.50
    colors = {"box_loss": "#2563eb", "cls_loss": "#dc2626", "dfl_loss": "#16a34a"}

    def points(values: list[float], left: int) -> str:
        result = []
        for epoch, value in zip(epochs, values):
            x = left + (epoch - 1) * panel_width / (epochs[-1] - 1)
            y = bottom - (value - y_min) * (bottom - top) / (y_max - y_min)
            result.append(f"{x:.1f},{y:.1f}")
        return " ".join(result)

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<style>text{font-family:Arial,sans-serif;fill:#0f172a}.title{font-size:30px;font-weight:700}.panel{font-size:22px;font-weight:700}.axis{font-size:14px;fill:#475569}.legend{font-size:15px}.note{font-size:14px;fill:#64748b}</style>',
        '<text x="700" y="48" text-anchor="middle" class="title">SH17 YOLOv9-e — 135-epoch loss history</text>',
    ]

    for left, prefix, title in zip(panel_lefts, ("train", "val"), ("Training losses", "Validation losses")):
        svg.append(f'<text x="{left + panel_width / 2}" y="94" text-anchor="middle" class="panel">{title}</text>')
        for tick in (0.3, 0.6, 0.9, 1.2, 1.5):
            y = bottom - (tick - y_min) * (bottom - top) / (y_max - y_min)
            svg.extend([
                f'<line x1="{left}" y1="{y:.1f}" x2="{left + panel_width}" y2="{y:.1f}" stroke="#e2e8f0"/>',
                f'<text x="{left - 12}" y="{y + 5:.1f}" text-anchor="end" class="axis">{tick:.1f}</text>',
            ])
        for tick in (1, 25, 50, 75, 100, 125, 135):
            x = left + (tick - 1) * panel_width / (epochs[-1] - 1)
            svg.extend([
                f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{bottom}" stroke="#f1f5f9"/>',
                f'<text x="{x:.1f}" y="584" text-anchor="middle" class="axis">{tick}</text>',
            ])
        svg.extend([
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="#334155"/>',
            f'<line x1="{left}" y1="{bottom}" x2="{left + panel_width}" y2="{bottom}" stroke="#334155"/>',
            f'<text x="{left + panel_width / 2}" y="615" text-anchor="middle" class="axis">Epoch</text>',
        ])
        for loss_name, label in (("box_loss", "Box loss"), ("cls_loss", "Classification loss"), ("dfl_loss", "DFL loss")):
            svg.append(f'<polyline points="{points(history[f"{prefix}/{loss_name}"], left)}" fill="none" stroke="{colors[loss_name]}" stroke-width="3" stroke-linejoin="round"/>')
        for row, (loss_name, label) in enumerate((("box_loss", "Box loss"), ("cls_loss", "Classification loss"), ("dfl_loss", "DFL loss"))):
            legend_y = 140 + row * 26
            legend_x = left + panel_width - 145
            svg.extend([
                f'<line x1="{legend_x}" y1="{legend_y}" x2="{legend_x + 30}" y2="{legend_y}" stroke="{colors[loss_name]}" stroke-width="4"/>',
                f'<text x="{legend_x + 40}" y="{legend_y + 5}" class="legend">{label}</text>',
            ])

    svg.extend([
        '<text x="700" y="640" text-anchor="middle" class="note">Actual values extracted safely from the training history embedded in the released checkpoint</text>',
        '</svg>',
    ])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(svg), encoding="utf-8")


if __name__ == "__main__":
    main()
