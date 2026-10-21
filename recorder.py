"""Recording, clip metadata and the reading logger (TRD section 9). No Qt: usable from any thread.

The means CSV is written on the calling (capture) thread: it is a few bytes per frame. Video encoding runs on its
own thread behind a queue, so the capture thread never waits for the encoder (opening a lossless writer and
flushing the fps-probe frames used to stall capture for about 0.3 s at the start of every recording).

A recording is three files that share a stamp, all under recordings/:
  <stamp>_means.csv   t, R, G, B, face_found, relock  per frame, from the live uncompressed frames (what evaluation uses)
  <stamp>.mkv         lossless FFV1 video (or <stamp>.avi MJPG if FFV1 is unavailable, with a warning)
  <stamp>_meta.json   the settings the clip was captured with, plus the reference fields
"""
from __future__ import annotations

import csv
import json
import logging
import os
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

import config
from models import FrameSample

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent

REF_FIELDS = ("ref_bpm", "device", "light_frame", "notes")


def project_dir(name: str) -> Path:
    path = ROOT / name
    path.mkdir(exist_ok=True)
    return path


def config_snapshot() -> dict:
    """Every upper-case, JSON-serialisable value in config: everything that could change the analysis."""
    out = {}
    for key in dir(config):
        if key.isupper():
            try:
                out[key] = json.loads(json.dumps(getattr(config, key)))
            except TypeError:
                pass
    return out


def settings_snapshot(method: str) -> dict:
    """The settings P6 evaluation needs to know about a clip."""
    return {"ROI_SET": config.ROI_SET, "FREEZE_ROI": config.FREEZE_ROI, "BAND_LO": config.BAND_LO,
            "BAND_HI": config.BAND_HI, "WINDOW_SEC": config.WINDOW_SEC, "MIN_SEC": config.MIN_SEC,
            "method": method}


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)                     # atomic: a crash never leaves half a meta file


def update_meta(path: Path | str, **fields) -> dict:
    """Update top-level meta fields (the reference fields, typically) in an existing meta file."""
    path = Path(path)
    meta = json.loads(path.read_text())
    meta.update(fields)
    _write_json(path, meta)
    return meta


class Recorder:
    """Writes the means CSV on every frame and the lossless video; `write` is called from the capture thread."""

    def __init__(self, method: str, source: str, light_frame: bool, ref: dict | None = None,
                 directory: Path | None = None):
        self.directory = directory or project_dir(config.RECORDINGS_DIR)
        self.stamp = time.strftime("%Y%m%d_%H%M%S")
        self.csv_path = self.directory / f"{self.stamp}_means.csv"
        self.meta_path = self.directory / f"{self.stamp}_meta.json"
        self.video_path: Path | None = None
        self.codec: str | None = None
        self.warnings: list[str] = []
        self.frames = 0
        self._t0: float | None = None
        self._t_last = 0.0
        self.video_fps: float | None = None
        self.max_backlog = 0                                    # most frames ever waiting for the encoder
        self._writer: cv2.VideoWriter | None = None
        self._video_failed = False                              # tried to open a writer and could not: stop trying
        self._pending: list[tuple[float, np.ndarray]] = []     # frames held until the real fps is known
        self._queue: queue.Queue = queue.Queue()
        self._video_error: str | None = None
        self._thread = threading.Thread(target=self._video_loop, name="recorder-video", daemon=True)
        self._csv = open(self.csv_path, "w", newline="")
        self._csv.write("t,R,G,B,face_found,relock\n")
        ref = ref or {}
        self.meta = {
            "stamp": self.stamp, "created": datetime.now().isoformat(timespec="seconds"), "source": source,
            "ref_bpm": ref.get("ref_bpm"), "device": ref.get("device", ""), "light_frame": light_frame,
            "notes": ref.get("notes", ""),
            "settings": settings_snapshot(method), "config": config_snapshot(),
            "files": {"means": self.csv_path.name, "video": None},
        }
        _write_json(self.meta_path, self.meta)
        self._thread.start()

    # ---- per frame

    def write(self, frame_bgr: np.ndarray, sample: FrameSample) -> None:
        if self._t0 is None:
            self._t0 = sample.t
        self._t_last = sample.t
        if sample.rgb is not None:
            row = f"{sample.t - self._t0:.6f},{sample.rgb[0]:.5f},{sample.rgb[1]:.5f},{sample.rgb[2]:.5f},{int(sample.face_found)},{int(sample.relock)}\n"
        else:
            row = f"{sample.t - self._t0:.6f},,,,{int(sample.face_found)},{int(sample.relock)}\n"
        self._csv.write(row)
        self.frames += 1
        if self.frames % config.FPS_REQUEST == 0:
            self._csv.flush()
        self._queue.put((sample.t, frame_bgr))        # not copied: the capture loop never modifies a frame after this
        self.max_backlog = max(self.max_backlog, self._queue.qsize())

    def _measured_fps(self) -> float:
        if len(self._pending) >= 2:
            span = self._pending[-1][0] - self._pending[0][0]
            if span > 0:
                return (len(self._pending) - 1) / span
        return float(config.FPS_REQUEST)

    def _open_video(self, shape: tuple[int, ...]) -> None:
        """Lossless FFV1 if this OpenCV build can write it, otherwise high-quality MJPG (lossy, with a warning)."""
        h, w = shape[:2]
        fps = self._measured_fps()          # the writer's fps defines playback timing, so it must be the real one
        path = self.directory / f"{self.stamp}.mkv"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"FFV1"), fps, (w, h))
        if writer.isOpened():
            self.codec = "FFV1 (lossless)"
        else:
            path = self.directory / f"{self.stamp}.avi"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
            writer.set(cv2.VIDEOWRITER_PROP_QUALITY, config.RECORD_MJPG_QUALITY)
            self.codec = f"MJPG quality {config.RECORD_MJPG_QUALITY} (lossy)"
            msg = "FFV1 unavailable; fell back to lossy MJPG. Lossy compression can erase the pulse signal: evaluate from the means CSV"
            self.warnings.append(msg)
            log.warning(msg)
        if not writer.isOpened():
            self.warnings.append("No video writer could be opened; only the means CSV was recorded")
            log.warning(self.warnings[-1])
            self._video_failed = True
            return
        self._writer, self.video_path, self.video_fps = writer, path, fps

    def _video_loop(self) -> None:
        """Encoder thread: hold the first RECORD_FPS_PROBE_FRAMES to measure the real fps, then write everything."""
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    break
                if self._video_failed:
                    continue
                t, frame = item
                if self._writer is None:
                    self._pending.append((t, frame))
                    if len(self._pending) < config.RECORD_FPS_PROBE_FRAMES:
                        continue
                    self._open_video(frame.shape)
                    for _, f in self._pending:
                        if self._writer is not None:
                            self._writer.write(f)
                    self._pending.clear()
                else:
                    self._writer.write(frame)
            if self._writer is None and self._pending and not self._video_failed:   # clip shorter than the probe
                self._open_video(self._pending[-1][1].shape)
                for _, f in self._pending:
                    if self._writer is not None:
                        self._writer.write(f)
            self._pending.clear()
        except Exception as e:                                  # never let the encoder take the capture down
            self._video_error = f"video encoding failed: {e}"
            log.exception("video encoding failed")
        finally:
            if self._writer is not None:
                self._writer.release()

    # ---- end

    def close(self, method: str | None = None, ref: dict | None = None) -> dict:
        """Flush everything and complete the meta file. Safe to call once; returns the final meta."""
        self._queue.put(None)                                  # drain the encoder, then finish
        self._thread.join()
        self._csv.close()
        duration = self._t_last - self._t0 if self._t0 is not None else 0.0
        meta = json.loads(self.meta_path.read_text())          # keep any reference edits made while recording
        meta.update({
            "duration_sec": round(duration, 3), "frames": self.frames,
            "measured_fps": round((self.frames - 1) / duration, 3) if duration > 0 and self.frames > 1 else None,
            "method_at_stop": method, "warnings": self.warnings + ([self._video_error] if self._video_error else []),
            "video_max_backlog_frames": self.max_backlog,
            "files": {"means": self.csv_path.name, "video": self.video_path.name if self.video_path else None},
            "video": {"codec": self.codec, "fps": self.video_fps},
        })
        for key in REF_FIELDS:
            if ref and key in ref:
                meta[key] = ref[key]
        _write_json(self.meta_path, meta)
        self.meta = meta
        return meta


READING_COLUMNS = ("time", "method", "bpm_smooth", "ref_bpm", "abs_error", "snr_db", "light_frame")


def log_reading(method: str, bpm_smooth: float, ref_bpm: float, snr_db: float | None, light_frame: bool,
                path: Path | None = None) -> dict:
    """Append one row to results/readings.csv (created with a header if needed)."""
    path = path or project_dir(config.RESULTS_DIR) / config.READINGS_CSV
    row = {"time": datetime.now().isoformat(timespec="seconds"), "method": method,
           "bpm_smooth": f"{bpm_smooth:.1f}", "ref_bpm": f"{ref_bpm:g}",
           "abs_error": f"{abs(bpm_smooth - ref_bpm):.1f}",
           "snr_db": "" if snr_db is None else f"{snr_db:.1f}", "light_frame": "on" if light_frame else "off"}
    new = not path.exists()
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=READING_COLUMNS)
        if new:
            writer.writeheader()
        writer.writerow(row)
    return row
