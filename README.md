# Industrial PPE Detection — SH17 YOLOv9-e

This repository includes a ready-to-use industrial Personal Protective Equipment (PPE) detection model based on **YOLOv9-e**, trained by the SH17 dataset authors on industrial and construction imagery.

> The model file is distributed through **GitHub Releases** because it is approximately 112 MB and exceeds GitHub's normal 100 MB repository-file limit.

## Download the model

Download the checkpoint from the repository release:

**[Download `SH17_YOLOv9e_PPE_17class.pt`](https://github.com/Usmanhassan7654/Usman-hassan/releases/download/ppe-v1.0/SH17_YOLOv9e_PPE_17class.pt)**

You can also download it from the command line:

```bash
curl -L -o SH17_YOLOv9e_PPE_17class.pt \
  https://github.com/Usmanhassan7654/Usman-hassan/releases/download/ppe-v1.0/SH17_YOLOv9e_PPE_17class.pt
```

Verify the downloaded file:

```bash
sha256sum SH17_YOLOv9e_PPE_17class.pt
```

Expected SHA-256:

```text
5ac6ac236da0f5cee84418f38170de67e314404f7a63a97c74ba5d172e33f39d
```

## What the model can detect

The checkpoint detects 17 PPE, person, body-region and workplace-object classes:

| ID | Detection class | ID | Detection class |
|---:|---|---:|---|
| 0 | Person | 9 | Gloves |
| 1 | Ear | 10 | Helmet |
| 2 | Ear muffs | 11 | Hands |
| 3 | Face | 12 | Head |
| 4 | Face guard | 13 | Medical suit |
| 5 | Face mask | 14 | Shoes |
| 6 | Foot | 15 | Safety suit |
| 7 | Tool | 16 | Safety vest |
| 8 | Glasses |  |  |

Typical applications include:

- Helmet, safety-vest, glove, glasses, mask and footwear monitoring
- Worker and body-region detection
- PPE compliance support for factories, warehouses and construction sites
- CCTV, recorded-video, webcam and RTSP-stream analysis
- Person-to-PPE association combined with tracking

### Important limitation

This model detects visible equipment. It does **not** directly contain `no-helmet`, `no-vest`, `no-gloves` or safety-harness classes. Missing-PPE violations should be inferred by associating detected equipment with each tracked worker and confirming the result across multiple frames. Harness detection requires further annotated data and fine-tuning.

## Published accuracy

These validation results were reported by the SH17 checkpoint authors on 1,620 validation images containing 15,358 annotated instances:

| Metric | Result |
|---|---:|
| Precision | 81.0% |
| Recall | 65.0% |
| mAP@50 | 70.9% |
| mAP@50–95 | 48.7% |

Accuracy can be lower on distant CCTV cameras, night scenes, severe occlusion and industrial sites that differ from the training data. Evaluate and fine-tune the model using footage from the target facility before production deployment.

## Training and validation loss chart

The following chart was generated from the 135-epoch training history embedded in the released checkpoint. It shows the actual box, classification and distribution-focal-loss histories—not estimated values.

![YOLOv9-e SH17 training and validation loss](assets/sh17_yolo9e_loss_chart.svg)

## Installation

Python 3.9–3.11 is recommended.

```bash
git clone https://github.com/Usmanhassan7654/Usman-hassan.git
cd Usman-hassan
pip install -r requirements.txt
```

Download the model using the release link above and place it in the repository root.

## Run detection

Image:

```bash
python predict_ppe.py --source image.jpg --show
```

Video:

```bash
python predict_ppe.py --source video.mp4 --show
```

Webcam:

```bash
python predict_ppe.py --source 0 --show
```

RTSP CCTV stream:

```bash
python predict_ppe.py --source "rtsp://username:password@camera-ip/stream" --show
```

For distant CCTV workers, start with `--imgsz 1280`:

```bash
python predict_ppe.py --source video.mp4 --imgsz 1280 --conf 0.25 --show
```

Outputs are saved under `runs/ppe/`.

## Model provenance

- Dataset and original checkpoints: [SH17 dataset repository](https://github.com/ahmadmughees/SH17dataset)
- Dataset size: 8,099 annotated images and 75,994 object instances
- Checkpoint: YOLOv9-e
- Model checksum: recorded above

The SH17 dataset is published under **CC BY-NC-SA 4.0**. Review the dataset, checkpoint, Ultralytics and dependency licenses before commercial use.
