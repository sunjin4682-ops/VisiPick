"""
Camera2 — side-view pin inspection on a backlit silhouette.
(염재니 비전 이식 — 통합방향 A. 김선진 defect_detector(더미) 자리를 측면 핀검사로 대체)

Algorithm (simple + robust enough for DIP-style parts):
  1. blur + Canny -> binary edge map
  2. project edges onto x-axis -> column histogram
  3. locate pin tips by local maxima above an adaptive threshold
  4. compute neighbour gap statistics + tip-y deviation
  5. flag bent / missing / unevenly spaced pins

Verdict
-------
  - NORMAL : pin count matches expected, gap CV < tolerance, all tips on
             same y-line within `tip_y_tolerance_px`
  - BENT   : tip count mismatch or excessive gap CV or tip-y outlier
  - UNKNOWN: no pins detected

이식 시 변경점 (인프라는 김선진 것 사용):
  - 로깅: 김선진 src.utils.logger.setup_logger 사용.
  - 공개 PinInspector 파사드: 인자 없는 생성자 PinInspector() 지원
    (state_machine 이 PinInspector() 로 생성 — config.vision.pin_inspector 로드).
  - inspect_side(frame, part) -> dict 어댑터 추가 (Decision.evaluate 의 side 입력).
  - dummy_mode=True(장비 없는 시연) 폴백 분기 — 50회 시연 안전판.
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from src.utils.logger import setup_logger
from src.utils.config_loader import config

log = setup_logger("pin_inspector")

# 더미(장비 없는 시연) 분기 — 측면 핀휨 모사 비율
_DUMMY_BENT_RATE = 0.07


@dataclass
class PinResult:
    verdict: str = "UNKNOWN"       # "NORMAL" | "BENT" | "UNKNOWN"
    pin_count: int = 0
    expected_count: int = 0
    gap_mean_px: float = 0.0
    gap_cv: float = 0.0            # coefficient of variation
    tip_y_range_px: int = 0
    bbox: Optional[Tuple[int, int, int, int]] = None
    reasons: List[str] = field(default_factory=list)


# ---------- Core silhouette pin detector --------------------------------------

class _PinDetector:
    """염재니 PinInspector 알고리즘 본체. cfg['pin_inspector'] 키를 읽는다."""

    def __init__(self, cfg: dict) -> None:
        p = cfg["pin_inspector"]
        self.canny_low = int(p["canny_low"])
        self.canny_high = int(p["canny_high"])
        self.blur = int(p["blur_ksize"]) | 1   # ensure odd
        self.expected: Dict[str, int] = dict(p["expected_pin_count"])
        self.gap_tol = float(p["pin_gap_tolerance_pct"]) / 100.0
        self.tip_y_tol = int(p["tip_y_tolerance_px"])

    def _find_pins(self, edges: np.ndarray) -> Tuple[List[int], List[int]]:
        """Return (column-x positions of pin tips, y-coordinate of each tip)."""
        h, w = edges.shape
        # column projection of edge density in lower 45% (closer to pins)
        roi = edges[int(h * 0.55):, :]
        col = roi.sum(axis=0).astype(np.float32)
        if col.max() == 0:
            return [], []
        col /= col.max()
        # peaks: local max > 0.4 with min distance 6 px
        peaks: List[int] = []
        last = -10
        thresh = 0.40
        for x in range(1, w - 1):
            if col[x] >= thresh and col[x] >= col[x - 1] and col[x] >= col[x + 1]:
                if x - last > 6:
                    peaks.append(x)
                    last = x
        # tip y: lowest edge in that column (largest y) within ROI
        tip_ys: List[int] = []
        for x in peaks:
            ys = np.where(edges[:, x] > 0)[0]
            tip_ys.append(int(ys.max()) if len(ys) else 0)
        return peaks, tip_ys

    def inspect(self, frame: np.ndarray, part: Optional[str] = None) -> PinResult:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        blur = cv2.GaussianBlur(gray, (self.blur, self.blur), 0)
        edges = cv2.Canny(blur, self.canny_low, self.canny_high)
        # crop to silhouette via column where ANY edge exists
        cols = np.where(edges.any(axis=0))[0]
        rows = np.where(edges.any(axis=1))[0]
        if cols.size < 10 or rows.size < 10:
            return PinResult(reasons=["no_edges"])
        x0, x1 = int(cols.min()), int(cols.max())
        y0, y1 = int(rows.min()), int(rows.max())
        roi_edges = edges[y0:y1 + 1, x0:x1 + 1]
        peaks, tip_ys = self._find_pins(roi_edges)
        pin_count = len(peaks)
        expected = self.expected.get(part or "", 0)
        reasons: List[str] = []
        gap_mean = gap_cv = 0.0
        if pin_count >= 2:
            gaps = np.diff(peaks).astype(np.float32)
            gap_mean = float(gaps.mean())
            gap_cv = float(gaps.std() / max(gap_mean, 1e-3))
        tip_y_range = (max(tip_ys) - min(tip_ys)) if tip_ys else 0

        verdict = "NORMAL"
        if expected and abs(pin_count - expected) > 1:
            verdict = "BENT"
            reasons.append(f"pin_count={pin_count} vs expected={expected}")
        if pin_count >= 2 and gap_cv > self.gap_tol:
            verdict = "BENT"
            reasons.append(f"gap_cv={gap_cv:.2f} > {self.gap_tol:.2f}")
        if tip_y_range > self.tip_y_tol:
            verdict = "BENT"
            reasons.append(f"tip_y_range={tip_y_range}px > {self.tip_y_tol}px")
        if pin_count == 0:
            verdict = "UNKNOWN"
            reasons.append("no_pins_detected")

        return PinResult(
            verdict=verdict,
            pin_count=pin_count,
            expected_count=expected,
            gap_mean_px=gap_mean,
            gap_cv=gap_cv,
            tip_y_range_px=tip_y_range,
            bbox=(x0, y0, x1 - x0, y1 - y0),
            reasons=reasons,
        )


# ---------- Public façade -----------------------------------------------------

class PinInspector:
    """측면 핀검사 파사드.

    state_machine 이 PinInspector() (인자 없음) 로 생성하므로 cfg 미지정 시
    config.vision 을 내부에서 로드한다. config.vision.pin_inspector 가 없으면
    KeyError 대신 더미 폴백으로 동작한다(시연 안전판).
    """

    def __init__(self, cfg: Optional[dict] = None) -> None:
        self._cfg = cfg if cfg is not None else config["vision"]
        self._dummy = bool(self._cfg.get("dummy_mode", False))
        self._impl = None

        if self._dummy:
            log.info("PinInspector 더미 모드 (장비 없는 시연 안전판)")
            return
        try:
            self._impl = _PinDetector(self._cfg)
        except KeyError as e:
            log.warning(f"pin_inspector 설정 누락({e}) → 더미 폴백")
            self._dummy = True

    # ── PinResult 반환 ────────────────────────────────────────────────────
    def inspect(self, frame, part: Optional[str] = None) -> PinResult:
        if self._dummy or self._impl is None:
            return self._dummy_result()
        if frame is None:
            return PinResult(reasons=["no_frame"])  # 미검출 — UNKNOWN
        return self._impl.inspect(frame, part)

    # ── side 딕셔너리 어댑터 (염재니 Decision.evaluate side 입력) ─────────
    def inspect_side(self, frame, part: Optional[str] = None) -> dict:
        """측면 비전 → Decision side 딕셔너리.

        반환: {"verdict","pin_count","gap_cv","tip_y_range_px"}
        verdict ∈ {"NORMAL","BENT","UNKNOWN"}
        """
        r = self.inspect(frame, part)
        return {
            "verdict":        r.verdict,
            "pin_count":      r.pin_count,
            "gap_cv":         r.gap_cv,
            "tip_y_range_px": r.tip_y_range_px,
        }

    # ── 더미 폴백 (장비/카메라 없이 시연) ─────────────────────────────────
    def _dummy_result(self) -> PinResult:
        if random.random() < _DUMMY_BENT_RATE:
            log.debug("[더미] 핀검사: BENT")
            return PinResult(verdict="BENT", pin_count=random.randint(6, 14),
                             gap_cv=round(random.uniform(0.35, 0.6), 2),
                             tip_y_range_px=random.randint(12, 30),
                             reasons=["dummy_bent"])
        log.debug("[더미] 핀검사: NORMAL")
        return PinResult(verdict="NORMAL", pin_count=random.choice([8, 14, 16]),
                         gap_cv=round(random.uniform(0.02, 0.12), 2),
                         tip_y_range_px=random.randint(1, 6))
