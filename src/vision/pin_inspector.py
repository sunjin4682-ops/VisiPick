"""
Camera2 — side-view pin inspection.
(염재니 비전 이식 — 통합방향 A. 김선진 defect_detector(더미) 자리를 측면 핀검사로 대체)

부품별 핀 방향(pin_direction)에 따라 검출 방식이 다르다
──────────────────────────────────────────────────────────────────────────────
  "down"  (DIP IC) — 핀이 아래를 향함:
    1. blur + Canny → edge map
    2. 하단 45% 컬럼 투영 → 핀 x위치(피크)
    3. Otsu 실루엣 최하단 픽셀 → 핀 끝점 y
    4. 이웃 간격 CV + 끝점 y 편차로 휨 판정

  "toward_camera" (터미널블록) — 핀이 카메라를 향함:
    1. HSV 색상으로 몸체(파란색) 분리 → 안정적 ROI (배경 잡음 무시, 박스 안흔들림)
    2. ROI 안에서 '밝고 채도 낮은' 금속 픽셀 마스크 → 은색 핀
    3. 컨투어 → 핀 중심 (cx, cy) 수집
    4. x 간격 CV + y 정렬 편차(polyfit 잔차) + 핀 수로 휨 판정
       · 핀이 휘면 → 중심이 옆으로/위아래로 어긋남 → gap_cv↑ 또는 y편차↑

Verdict
-------
  NORMAL : 핀 수 일치(허용오차 이내), gap CV < tol, y 정렬 편차 < tol
  BENT   : 핀 수 불일치 / 간격 불균일 / 정렬 이탈
  UNKNOWN: 핀(또는 몸체) 미검출

이식 시 변경점 (인프라는 김선진 것 사용):
  - 로깅: 김선진 src.utils.logger.setup_logger 사용.
  - 인자 없는 PinInspector() 지원 (state_machine 이 그렇게 생성).
  - inspect_side(frame, part) -> dict 어댑터 (Decision.evaluate 의 side 입력).
  - dummy_mode=True 폴백 (장비 없는 시연 안전판).
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


# ---------- Core detector -----------------------------------------------------

class _PinDetector:
    """염재니 PinInspector 알고리즘 본체. cfg['pin_inspector'] 키를 읽는다."""

    def __init__(self, cfg: dict) -> None:
        p = cfg["pin_inspector"]
        self.canny_low  = int(p["canny_low"])
        self.canny_high = int(p["canny_high"])
        self.blur       = int(p["blur_ksize"]) | 1   # ensure odd
        self.expected: Dict[str, int] = dict(p["expected_pin_count"])
        self.gap_tol   = float(p["pin_gap_tolerance_pct"]) / 100.0
        self.tip_y_tol = int(p["tip_y_tolerance_px"])

        # "down" 모드 피크 파라미터
        self.peak_thresh   = float(p.get("peak_thresh",    0.40))
        self.peak_min_dist = int(p.get("peak_min_dist_px", 6))
        self.tip_window    = int(p.get("tip_window_px",    4))

        # 부품별 방향 / 핀 수 허용오차
        self.pin_direction: Dict[str, str] = dict(p.get("pin_direction", {}))
        self.pin_count_tolerance: Dict[str, int] = {
            k: int(v) for k, v in p.get("pin_count_tolerance", {}).items()
        }

        # "toward_camera" — 몸체 색상 분리 파라미터 (부품별)
        self.color_segment: Dict[str, dict] = dict(p.get("color_segment", {}))
        self.min_body_area = int(p.get("min_body_area_px2", 2000))

        # "toward_camera" — 은색 핀 마스크 파라미터.
        # 핵심: 파란 몸체는 채도 높음, 은색 핀은 채도 낮음 → '몸체영역 안 채도낮은 픽셀=핀'.
        # 밝기(v)보다 채도(s)가 더 안정적 신호. 마스크를 몸체영역(+아래 리드)으로 가둬 배경 제거.
        m = p.get("metal_pin", {})
        self.metal_v_min    = int(m.get("v_min",         90))   # 밝기 하한(그림자/크레비스 제거)
        self.metal_s_max    = int(m.get("s_max",         90))   # 채도 상한(은색=낮음, 파란몸체=높음)
        self.metal_min_area = int(m.get("min_area_px2",  20))
        self.metal_max_area = int(m.get("max_area_px2", 8000))
        self.metal_lead_ext = int(m.get("lead_extend_px", 40))  # 몸체영역을 아래로 늘려 리드 포함
        # 핀 = 상단 노출 금속 + 그 아래로 이어진 리드. 세로로 닫아(close) 한 덩어리로 잇고,
        # 짧은 반사는 최소 높이로 거른다. 휨은 '상단 x ↔ 리드끝 x' 좌우편차(lean)로 잡음.
        self.metal_close_h   = int(m.get("close_h_px",   81))   # 상단금속·리드 세로 연결 커널 높이
        self.metal_band      = int(m.get("band_px",       8))   # 위/아래 x 추정용 띠 두께
        self.metal_min_h     = int(m.get("min_height_px", 20))  # 핀 최소 세로길이(짧은 반사 제거)
        self.metal_lean_tol  = int(m.get("lean_tol_px",  30))   # |리드끝x - 상단x| 이상이면 휨

    # ── 공통 판정 ─────────────────────────────────────────────────────────────

    def _verdict(self, xs: List[int], ys: List[int], part: Optional[str]) -> PinResult:
        """핀 x중심 리스트 + y중심 리스트로 판정. 두 모드 공통."""
        pin_count = len(xs)
        expected  = self.expected.get(part or "", 0)
        count_tol = self.pin_count_tolerance.get(part or "", 1)
        reasons: List[str] = []
        gap_mean = gap_cv = 0.0
        if pin_count >= 2:
            gaps     = np.diff(xs).astype(np.float32)
            gap_mean = float(gaps.mean())
            gap_cv   = float(gaps.std() / max(gap_mean, 1e-3))
        # y 정렬 편차: polyfit 잔차(전체 기울기는 무시, 혼자 어긋난 핀만 잡힘)
        if pin_count >= 3:
            xa = np.asarray(xs, dtype=np.float32)
            ya = np.asarray(ys, dtype=np.float32)
            a, b = np.polyfit(xa, ya, 1)
            tip_y_range = int(np.abs(ya - (a * xa + b)).max())
        else:
            tip_y_range = (max(ys) - min(ys)) if ys else 0

        verdict = "NORMAL"
        if pin_count == 0:
            verdict = "UNKNOWN"
            reasons.append("no_pins_detected")
        else:
            if expected and abs(pin_count - expected) > count_tol:
                verdict = "BENT"
                reasons.append(f"pin_count={pin_count} vs expected={expected} (tol={count_tol})")
            if pin_count >= 2 and gap_cv > self.gap_tol:
                verdict = "BENT"
                reasons.append(f"gap_cv={gap_cv:.2f} > {self.gap_tol:.2f}")
            if tip_y_range > self.tip_y_tol:
                verdict = "BENT"
                reasons.append(f"tip_y_range={tip_y_range}px > {self.tip_y_tol}px")

        return PinResult(verdict=verdict, pin_count=pin_count, expected_count=expected,
                         gap_mean_px=gap_mean, gap_cv=gap_cv, tip_y_range_px=tip_y_range,
                         reasons=reasons)

    # ── "down" (DIP IC) ───────────────────────────────────────────────────────

    @staticmethod
    def _silhouette(blur: np.ndarray) -> np.ndarray:
        _, sil = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        return sil

    def _find_pins_down(self, edges, sil) -> Tuple[List[int], List[int]]:
        h, w = edges.shape
        roi = edges[int(h * 0.55):, :]
        col = roi.sum(axis=0).astype(np.float32)
        if col.max() == 0:
            return [], []
        col /= col.max()
        peaks: List[int] = []
        last = -10_000
        for x in range(1, w - 1):
            if col[x] >= self.peak_thresh and col[x] >= col[x - 1] and col[x] >= col[x + 1]:
                if x - last >= self.peak_min_dist:
                    peaks.append(x); last = x
        tip_ys: List[int] = []
        win = self.tip_window
        for x in peaks:
            lo, hi = max(0, x - win), min(w, x + win + 1)
            col_tips = []
            for xx in range(lo, hi):
                ys = np.where(sil[:, xx] > 0)[0]
                if len(ys):
                    col_tips.append(int(ys.max()))
            tip_ys.append(int(np.median(col_tips)) if col_tips else 0)
        return peaks, tip_ys

    def _inspect_down(self, frame, part) -> Tuple[PinResult, np.ndarray]:
        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        blur  = cv2.GaussianBlur(gray, (self.blur, self.blur), 0)
        edges = cv2.Canny(blur, self.canny_low, self.canny_high)
        sil   = self._silhouette(blur)
        cols = np.where(edges.any(axis=0))[0]
        rows = np.where(edges.any(axis=1))[0]
        if cols.size < 10 or rows.size < 10:
            return PinResult(reasons=["no_edges"]), sil
        x0, x1 = int(cols.min()), int(cols.max())
        y0, y1 = int(rows.min()), int(rows.max())
        peaks, tip_ys = self._find_pins_down(edges[y0:y1 + 1, x0:x1 + 1],
                                             sil[y0:y1 + 1, x0:x1 + 1])
        xs = [x0 + px for px in peaks]
        ys = [y0 + ty for ty in tip_ys]
        res = self._verdict(xs, ys, part)
        res.bbox = (x0, y0, x1 - x0, y1 - y0)
        return res, sil

    # ── "toward_camera" (터미널블록) ──────────────────────────────────────────

    def _segment_body(self, frame, part):
        """HSV 색상으로 몸체 분리.
        반환: (bbox, region) — region 은 핀(채도낮은 구멍)을 메운 '꽉 찬 몸체 영역'을
        아래로 lead_extend 만큼 늘린 마스크. metal 마스크를 여기로 가둬 배경을 제거한다.
        실패 시 (None, None)."""
        if frame.ndim != 3:
            return None, None
        c = self.color_segment.get(part or "", {})
        if not c:
            return None, None
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        lo = np.array([c.get("h_lo", 90),  c.get("s_min", 50), c.get("v_min", 40)], np.uint8)
        hi = np.array([c.get("h_hi", 130), 255, 255], np.uint8)
        mask = cv2.inRange(hsv, lo, hi)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  np.ones((5, 5),  np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            return None, None
        big = max(cnts, key=cv2.contourArea)
        if cv2.contourArea(big) < self.min_body_area:
            return None, None
        bbox = cv2.boundingRect(big)                  # (x, y, w, h)
        region = np.zeros(mask.shape, np.uint8)
        cv2.drawContours(region, [big], -1, 255, -1)  # 핀 구멍까지 메운 꽉 찬 몸체
        if self.metal_lead_ext > 0:                   # 몸체 아래로 늘려 매달린 리드 포함
            k = cv2.getStructuringElement(cv2.MORPH_RECT, (1, self.metal_lead_ext * 2 + 1))
            down = cv2.dilate(region, k)
            shift = np.zeros_like(region)             # 아래쪽으로만 확장(위는 유지)
            shift[self.metal_lead_ext:, :] = down[:-self.metal_lead_ext, :]
            region = cv2.bitwise_or(region, shift)
        return bbox, region

    def _metal_mask(self, frame, region) -> np.ndarray:
        """몸체영역(region) 안에서 채도 낮은 은색 금속 픽셀 마스크.
        파란 몸체(채도 높음)는 빠지고 은색 핀만 남는다. 배경은 region 으로 제외."""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        v, s = hsv[:, :, 2], hsv[:, :, 1]
        metal = ((v >= self.metal_v_min) & (s <= self.metal_s_max)).astype(np.uint8) * 255
        metal = cv2.bitwise_and(metal, region)
        metal = cv2.morphologyEx(metal, cv2.MORPH_OPEN,  np.ones((3, 3), np.uint8))
        metal = cv2.morphologyEx(metal, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        return metal

    def _find_pin_leads(self, metal) -> List[dict]:
        """금속 마스크 → 핀 리드 목록. 각 핀: 상단 금속 + 그 아래 리드를 한 덩어리로.

        반환 각 항목: {top_x, tip_x, tip_y, cx, lean}
          · top_x : 덩어리 최상단 띠의 x 평균 (상단 노출 금속 위치)
          · tip_x : 덩어리 최하단 띠의 x 평균 (리드 끝 위치)
          · lean  : |tip_x - top_x| — 리드가 옆으로 휜 정도(휨 판정 핵심)
        """
        # 세로로 닫아 상단 금속과 그 아래 리드를 한 컨투어로 연결
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, self.metal_close_h | 1))
        closed = cv2.morphologyEx(metal, cv2.MORPH_CLOSE, k)
        cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        pins: List[dict] = []
        band = self.metal_band
        for cnt in cnts:
            area = cv2.contourArea(cnt)
            if area < self.metal_min_area or area > self.metal_max_area:
                continue
            pts = cnt.reshape(-1, 2)
            ys = pts[:, 1]
            ymin, ymax = int(ys.min()), int(ys.max())
            if ymax - ymin < self.metal_min_h:        # 짧은 반사(상단 금속만) 제거 → 핀 아님
                continue
            top_x = float(pts[ys <= ymin + band][:, 0].mean())
            tip_x = float(pts[ys >= ymax - band][:, 0].mean())
            pins.append({
                "top_x": top_x, "tip_x": tip_x, "tip_y": ymax,
                "cx": int(pts[:, 0].mean()), "lean": abs(tip_x - top_x),
            })
        pins.sort(key=lambda pt: pt["top_x"])
        return pins

    def _verdict_metal(self, pins: List[dict], part: Optional[str]) -> PinResult:
        """toward_camera 판정: 핀 수 + 리드끝 간격 + 최대 lean(휨)."""
        n         = len(pins)
        expected  = self.expected.get(part or "", 0)
        count_tol = self.pin_count_tolerance.get(part or "", 1)
        reasons: List[str] = []
        tip_xs = [p["tip_x"] for p in pins]
        gap_mean = gap_cv = 0.0
        if n >= 2:
            gaps     = np.diff(tip_xs).astype(np.float32)
            gap_mean = float(gaps.mean())
            gap_cv   = float(gaps.std() / max(abs(gap_mean), 1e-3))
        max_lean = max((p["lean"] for p in pins), default=0.0)

        verdict = "NORMAL"
        if n == 0:
            verdict = "UNKNOWN"
            reasons.append("no_pins_detected")
        else:
            if expected and abs(n - expected) > count_tol:
                verdict = "BENT"
                reasons.append(f"pin_count={n} vs expected={expected} (tol={count_tol})")
            if n >= 2 and gap_cv > self.gap_tol:
                verdict = "BENT"
                reasons.append(f"gap_cv={gap_cv:.2f} > {self.gap_tol:.2f}")
            if max_lean > self.metal_lean_tol:
                verdict = "BENT"
                reasons.append(f"lean={max_lean:.0f}px > {self.metal_lean_tol}px")

        return PinResult(verdict=verdict, pin_count=n, expected_count=expected,
                         gap_mean_px=gap_mean, gap_cv=gap_cv,
                         tip_y_range_px=int(round(max_lean)),   # 표시용: 최대 휨(lean)
                         reasons=reasons)

    def _inspect_toward_camera(self, frame, part) -> Tuple[PinResult, np.ndarray, List[dict]]:
        bbox, region = self._segment_body(frame, part)
        extra: List[str] = []
        if bbox is None:                       # 색상 분리 실패 → 전체 프레임 폴백(튜닝용)
            h, w = frame.shape[:2]
            bbox = (0, 0, w, h)
            region = np.full((h, w), 255, np.uint8)
            extra.append("no_body_color")
        metal = self._metal_mask(frame, region)
        pins = self._find_pin_leads(metal)
        res = self._verdict_metal(pins, part)
        res.bbox = bbox
        res.reasons += extra
        return res, metal, pins

    # ── 메인 진입점 ─────────────────────────────────────────────────────────────

    def inspect(self, frame: np.ndarray, part: Optional[str] = None) -> PinResult:
        direction = self.pin_direction.get(part or "", "down")
        if direction == "toward_camera":
            res, _, _ = self._inspect_toward_camera(frame, part)
            return res
        res, _ = self._inspect_down(frame, part)
        return res

    def inspect_debug(self, frame: np.ndarray, part: Optional[str] = None):
        """튜닝/시각화 전용.
        반환: (PinResult, edges, pane_mask, tips[(x,y),...])
          pane_mask: down=실루엣, toward_camera=금속마스크 (live_pin 's' 패널 표시)
        """
        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        blur  = cv2.GaussianBlur(gray, (self.blur, self.blur), 0)
        edges = cv2.Canny(blur, self.canny_low, self.canny_high)
        direction = self.pin_direction.get(part or "", "down")

        if direction == "toward_camera":
            res, metal, pins = self._inspect_toward_camera(frame, part)
            # 리드 끝(tip) 표시 + 상단금속→리드끝 lean 선은 live_pin 이 그림
            tips = [(int(p["tip_x"]), int(p["tip_y"])) for p in pins]
            return res, edges, metal, tips

        res, sil = self._inspect_down(frame, part)
        tips: List[Tuple[int, int]] = []
        if res.bbox:
            x0, y0, bw, bh = res.bbox
            peaks, tip_ys = self._find_pins_down(edges[y0:y0 + bh + 1, x0:x0 + bw + 1],
                                                 sil[y0:y0 + bh + 1, x0:x0 + bw + 1])
            tips = [(x0 + px, y0 + ty) for px, ty in zip(peaks, tip_ys)]
        return res, edges, sil, tips


# ---------- Public façade -----------------------------------------------------

class PinInspector:
    """측면 핀검사 파사드. cfg 미지정 시 config.vision 로드. 설정 누락 시 더미 폴백."""

    def __init__(self, cfg: Optional[dict] = None) -> None:
        self._cfg   = cfg if cfg is not None else config["vision"]
        self._dummy = bool(self._cfg.get("dummy_mode", False))
        self._impl  = None
        if self._dummy:
            log.info("PinInspector 더미 모드 (장비 없는 시연 안전판)")
            return
        try:
            self._impl = _PinDetector(self._cfg)
        except KeyError as e:
            log.warning(f"pin_inspector 설정 누락({e}) → 더미 폴백")
            self._dummy = True

    def inspect(self, frame, part: Optional[str] = None) -> PinResult:
        if self._dummy or self._impl is None:
            return self._dummy_result()
        if frame is None:
            return PinResult(reasons=["no_frame"])
        return self._impl.inspect(frame, part)

    def inspect_side(self, frame, part: Optional[str] = None) -> dict:
        r = self.inspect(frame, part)
        return {
            "verdict":        r.verdict,
            "pin_count":      r.pin_count,
            "gap_cv":         r.gap_cv,
            "tip_y_range_px": r.tip_y_range_px,
        }

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
