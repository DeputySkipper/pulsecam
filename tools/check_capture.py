"""Headless P1 check: measured FPS, % frames with a face, std of the G trace, 3 annotated snapshots.

    python tools/check_capture.py                  # webcam, 10 s
    python tools/check_capture.py --file clip.mp4  # video file (not paced to real time)
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from capture import FileSource, WebcamSource  # noqa: E402
from face_roi import FaceROI  # noqa: E402

N_SNAPSHOTS = 3
CENTRE_DISCARD_SEC = 3.0     # skip the lock phase when measuring box-centre jitter


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--file", help="video file instead of the webcam")
    ap.add_argument("--camera", type=int, default=config.CAM_INDEX)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        source = FileSource(args.file) if args.file else WebcamSource(args.camera)
    except RuntimeError as e:
        print(f"FAILED: {e}")
        return 1

    face_roi = FaceROI()
    out_dir = ROOT / "debug"
    out_dir.mkdir(exist_ok=True)
    snapshot_at = [args.seconds * f for f in (0.3, 0.6, 0.9)]
    saved = 0

    ts, g_trace, found, centres = [], [], [], []
    relocks, frozen_segs, seg = [], [], []     # FREEZE_ROI: flags alternate lock-start / freeze
    t_start = None
    while True:
        item = source.read()
        if item is None:
            break
        t, frame = item
        t_start = t if t_start is None else t_start
        elapsed = t - t_start
        if elapsed > args.seconds:
            break
        sample = face_roi.process(frame, t)
        ts.append(t)
        found.append(sample.face_found)
        if sample.rgb is not None:
            g_trace.append(sample.rgb[1])
            if elapsed >= CENTRE_DISCARD_SEC:
                x, y, w, h = sample.face_box
                centres.append((x + w / 2, y + h / 2))
        if sample.relock:
            relocks.append(elapsed)
            if len(relocks) % 2 == 1 and len(seg) > 1:      # an odd flag is a lock start: the previous segment was frozen
                frozen_segs.append(seg)
            seg = []
        if sample.face_box is not None and len(relocks) % 2 == 0 and config.FREEZE_ROI:
            x, y, w, h = sample.face_box
            seg.append((x + w / 2, y + h / 2))
        if saved < N_SNAPSHOTS and elapsed >= snapshot_at[saved]:
            path = out_dir / f"snapshot_{saved + 1}.png"
            cv2.imwrite(str(path), sample.preview)
            saved += 1
    source.release()

    n = len(ts)
    if n < 2:
        print("FAILED: fewer than 2 frames captured (camera permission? file empty?)")
        return 1
    fps = (n - 1) / (ts[-1] - ts[0])
    face_pct = 100.0 * sum(found) / n
    g_std = float(np.std(g_trace)) if g_trace else 0.0
    if not args.file and isinstance(source, WebcamSource):
        print(f"Camera lock : {source.lock_result}")
    print(f"Frames      : {n} over {ts[-1] - ts[0]:.1f} s")
    print(f"Measured FPS: {fps:.1f}")
    print(f"Face found  : {face_pct:.1f}% of frames")
    print(f"G trace std : {g_std:.4f} (0-255 scale, {len(g_trace)} samples)")
    if centres:
        cx, cy = np.std(centres, axis=0)
        print(f"Box centre  : std x={cx:.2f} px, y={cy:.2f} px (after first {CENTRE_DISCARD_SEC:.0f} s, FREEZE_ROI={config.FREEZE_ROI})")
    if config.FREEZE_ROI:
        if len(relocks) % 2 == 0 and len(seg) > 1:
            frozen_segs.append(seg)
        within = max((float(np.std(g, axis=0).max()) for g in frozen_segs), default=float("nan"))
        print(f"ROI lock    : {len(relocks) // 2} freeze(s) at t={[round(r, 1) for r in relocks[1::2]]} s; "
              f"max centre std inside a frozen segment = {within:.2f} px (box centre std above includes jumps between locks)")
    print(f"Snapshots   : {saved} saved to {out_dir}")

    ok = face_pct >= 90.0 and g_std > 0.0
    print("GATE        :", "PASS" if ok else "CHECK: face < 90% or G trace flat")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
