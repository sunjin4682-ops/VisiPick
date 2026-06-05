"""
Camera1 classifier  (염재니 비전 이식 — 통합방향 A)

Two pipelines coexist:
  1) "classical" — MOG2 background subtraction -> contour ROI -> area,
     aspect ratio, Hu-moments scored against config-defined references.
  2) "yolo"     — Ultralytics YOLOv8 best.pt with 7 fine-grained classes
     collapsed onto 4 coarse part types (IC / Capacitor / Heatsink /
     TerminalBlock) plus a verdict (PASS / REJECT) coming from the label.

Mode is selected from config.vision.mode. Classical is the spec-required
fallback and runs without GPU; YOLO is the production path when best.pt
is available.

이식 시 변경점 (인프라는 김선진 것 사용):
  - 로깅: 김선진 src.utils.logger.setup_logger 사용 (날짜별 롤링 로그).
  - 공개 Classifier 파사드: 인자 없는 생성자 Classifier() 지원
    (state_machine 이 Classifier() 로 생성 — config.vision 을 내부에서 로드).
  - classify_top(frame) -> dict 어댑터 추가 (염재니 Decision.evaluate 의 top 입력).
  - dummy_mode=True(장비 없는 시연) 폴백 분기 — 50회 시연 안전판.
  - yolo_model_path 상대경로를 프로젝트 루트 기준으로 해석.
"""
from __future__ import annotations
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from src.utils.logger import setup_logger
from src.utils.config_loader import config
from src.utils.part_map import PARTS_EN

log = setup_logger("classifier")

# 더미(장비 없는 시연) 분기 — 상부 카메라 1차 불량 모사 비율
_DUMMY_TOP_REJECT_RATE = 0.10


@dataclass
class ClassifyResult:
    part: Optional[str] = None        # "IC" | "Capacitor" | "Heatsink" | "TerminalBlock" | None
    verdict_hint: str = "UNKNOWN"     # "PASS" | "REJECT" | "UNKNOWN"  (from YOLO label only)
    confidence: float = 0.0
    bbox: Optional[Tuple[int, int, int, int]] = None  # x,y,w,h
    features: Dict[str, float] = field(default_factory=dict)
    raw_class: Optional[str] = None
    defect_classes: List[str] = field(default_factory=list)  # 한 프레임에서 검출된 '모든' 불량 클래스
    mode: str = "classical"


# ---------- Classical CV path -------------------------------------------------

class _ClassicalClassifier:
    """MOG2 -> contour -> (area, aspect, Hu) 4-class scoring."""

    def __init__(self, cfg: dict) -> None:
        m = cfg["mog2"]
        c = cfg["classical"]
        self.bg = cv2.createBackgroundSubtractorMOG2(
            history=m["history"],
            varThreshold=m["var_threshold"],
            detectShadows=m["detect_shadows"],
        )
        self.min_area = m["min_area_px"]
        self.max_area = m["max_area_px"]
        self.area_ranges = c["area_ranges"]
        self.aspect_ranges = c["aspect_ranges"]
        # Hu moments reference vectors as in config (log-scaled)
        self.hu_ref: Dict[str, np.ndarray] = {
            k: np.asarray(v, dtype=np.float64) for k, v in c["hu_ref"].items()
        }

    @staticmethod
    def _hu_log(moments_hu: np.ndarray) -> np.ndarray:
        # standard sign-preserving log scaling
        out = np.zeros_like(moments_hu, dtype=np.float64)
        for i, h in enumerate(moments_hu):
            if h == 0:
                out[i] = 0.0
            else:
                out[i] = -np.sign(h) * np.log10(abs(h))
        return out

    def _score_part(self, area: float, aspect: float, hu_log: np.ndarray) -> Tuple[str, float, Dict[str, float]]:
        scores: Dict[str, float] = {}
        for part, ref in self.hu_ref.items():
            a_lo, a_hi = self.area_ranges[part]
            ar_lo, ar_hi = self.aspect_ranges[part]
            # Penalty for out-of-range area/aspect (smooth, not hard reject)
            area_pen = 0.0
            if not (a_lo <= area <= a_hi):
                # distance to nearest edge relative to band width
                edge = a_lo if area < a_lo else a_hi
                area_pen = abs(area - edge) / max(a_hi - a_lo, 1.0)
            aspect_pen = 0.0
            if not (ar_lo <= aspect <= ar_hi):
                edge = ar_lo if aspect < ar_lo else ar_hi
                aspect_pen = abs(aspect - edge) / max(ar_hi - ar_lo, 1e-3)
            hu_dist = float(np.linalg.norm(hu_log - ref))
            # weighted distance — lower is better
            score = hu_dist + 1.5 * area_pen + 2.0 * aspect_pen
            scores[part] = score
        best = min(scores, key=scores.get)
        # confidence = softmaxed inverse distance
        inv = {k: math.exp(-v) for k, v in scores.items()}
        z = sum(inv.values()) or 1.0
        conf = inv[best] / z
        return best, conf, scores

    def classify(self, frame: np.ndarray) -> ClassifyResult:
        fg = self.bg.apply(frame)
        # cleanup mask
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        contours, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return ClassifyResult(mode="classical")
        cnt = max(contours, key=cv2.contourArea)
        area = float(cv2.contourArea(cnt))
        if not (self.min_area <= area <= self.max_area):
            return ClassifyResult(mode="classical", features={"area": area})
        x, y, w, h = cv2.boundingRect(cnt)
        aspect = max(w, h) / max(min(w, h), 1)
        moments = cv2.moments(cnt)
        hu = cv2.HuMoments(moments).flatten()
        hu_log = self._hu_log(hu)
        part, conf, _ = self._score_part(area, aspect, hu_log)
        return ClassifyResult(
            part=part,
            verdict_hint="UNKNOWN",  # classical CV can't tell orientation
            confidence=conf,
            bbox=(x, y, w, h),
            features={"area": area, "aspect": aspect,
                      **{f"hu{i}": float(hu_log[i]) for i in range(7)}},
            mode="classical",
        )


# ---------- YOLO path ---------------------------------------------------------

class _YoloClassifier:
    def __init__(self, cfg: dict) -> None:
        from ultralytics import YOLO  # lazy import — heavy
        self.model = YOLO(cfg["yolo_model_path"])
        self.conf = float(cfg["yolo_conf"])
        self.iou = float(cfg["yolo_iou"])
        self.imgsz = int(cfg["yolo_imgsz"])
        # 불량 클래스는 part 박스보다 신뢰도가 낮아도 잡아야 하므로 별도 임계값
        self.defect_min_conf = float(cfg.get("defect_min_conf", self.conf))
        self.class_map: Dict[str, Dict[str, str]] = cfg["yolo_class_map"]
        # cache class name list
        self.names: Dict[int, str] = self.model.names  # type: ignore[assignment]
        log.info(f"YOLO loaded: {cfg['yolo_model_path']} ({len(self.names)} classes)")

    def raw_detections(self, frame: np.ndarray) -> List[Dict[str, object]]:
        """모델이 한 프레임에서 뱉는 '모든' 박스를 그대로 반환 (진단용).

        classify() 는 argmax 단일 박스만 쓰므로, 불량 클래스가 part 박스에
        가려졌는지 확인할 때 이걸로 전체 검출을 본다.
        반환: [{"name": str, "conf": float, "bbox": (x,y,w,h)}, ...] (conf 내림차순)
        """
        results = self.model.predict(
            frame, conf=self.conf, iou=self.iou, imgsz=self.imgsz, verbose=False
        )
        out: List[Dict[str, object]] = []
        if not results or results[0].boxes is None:
            return out
        r = results[0]
        for i in range(len(r.boxes)):
            cls_id = int(r.boxes.cls[i].item())
            x1, y1, x2, y2 = r.boxes.xyxy[i].cpu().numpy().astype(int)
            out.append({
                "name": self.names.get(cls_id, str(cls_id)),
                "conf": float(r.boxes.conf[i].item()),
                "bbox": (int(x1), int(y1), int(x2 - x1), int(y2 - y1)),
            })
        out.sort(key=lambda d: d["conf"], reverse=True)
        return out

    def classify(self, frame: np.ndarray) -> ClassifyResult:
        results = self.model.predict(
            frame, conf=self.conf, iou=self.iou, imgsz=self.imgsz, verbose=False
        )
        if not results:
            return ClassifyResult(mode="yolo")
        r = results[0]
        if r.boxes is None or len(r.boxes) == 0:
            return ClassifyResult(mode="yolo")

        confs = r.boxes.conf.cpu().numpy()
        cls_ids = r.boxes.cls.cpu().numpy().astype(int)
        xyxy = r.boxes.xyxy.cpu().numpy().astype(int)

        # 모든 박스를 part(IC/CAP/HS/TB) / defect(Broken/Dented/Pinbent) 로 분리.
        # 단일 argmax 를 쓰면 신뢰도 높은 part 박스가 불량 박스를 가린다 → 전수 검사.
        part_idx: Optional[int] = None       # 최고신뢰 part 박스
        defect_idx: Optional[int] = None     # 최고신뢰 defect 박스 (defect_min_conf 이상만)
        defect_classes: List[str] = []       # 검출된 '모든' 불량 클래스(중복 제거, 한 부품에 2종 가능)
        for i in range(len(confs)):
            name = self.names.get(int(cls_ids[i]), str(int(cls_ids[i])))
            m = self.class_map.get(name, {})
            if "part" in m:
                if part_idx is None or confs[i] > confs[part_idx]:
                    part_idx = i
            elif m.get("verdict") == "REJECT" and confs[i] >= self.defect_min_conf:
                if defect_idx is None or confs[i] > confs[defect_idx]:
                    defect_idx = i
                if name not in defect_classes:
                    defect_classes.append(name)

        # 매핑된 part/defect 가 하나도 없으면(미지 클래스만) → 최고신뢰 박스로 폴백
        if part_idx is None and defect_idx is None:
            i = int(np.argmax(confs))
            name = self.names.get(int(cls_ids[i]), str(int(cls_ids[i])))
            m = self.class_map.get(name, {})
            x1, y1, x2, y2 = xyxy[i]
            return ClassifyResult(
                part=m.get("part"), verdict_hint=m.get("verdict", "UNKNOWN"),
                confidence=float(confs[i]),
                bbox=(int(x1), int(y1), int(x2 - x1), int(y2 - y1)),
                raw_class=name, mode="yolo",
            )

        # 부품 종류는 part 박스 우선(없으면 defect 박스 위치 사용)
        base_idx = part_idx if part_idx is not None else defect_idx
        base_name = self.names.get(int(cls_ids[base_idx]), str(int(cls_ids[base_idx])))
        part = self.class_map.get(base_name, {}).get("part")

        # 불량 박스가 하나라도 있으면 REJECT (신뢰도가 part 보다 낮아도)
        if defect_idx is not None:
            dname = self.names.get(int(cls_ids[defect_idx]), str(int(cls_ids[defect_idx])))
            dx1, dy1, dx2, dy2 = xyxy[defect_idx]
            return ClassifyResult(
                part=part,                                  # 종류는 유지(IC/CAP/...)
                verdict_hint="REJECT",
                confidence=float(confs[defect_idx]),
                bbox=(int(dx1), int(dy1), int(dx2 - dx1), int(dy2 - dy1)),  # 불량 위치
                raw_class=dname,                            # Pinbent / Broken / Dented (최고신뢰)
                defect_classes=defect_classes,              # 검출된 모든 불량(예: [Pinbent, Broken])
                mode="yolo",
            )

        # 불량 없음 → part 박스로 PASS
        bx1, by1, bx2, by2 = xyxy[base_idx]
        return ClassifyResult(
            part=part,
            verdict_hint=self.class_map.get(base_name, {}).get("verdict", "UNKNOWN"),
            confidence=float(confs[base_idx]),
            bbox=(int(bx1), int(by1), int(bx2 - bx1), int(by2 - by1)),
            raw_class=base_name,
            mode="yolo",
        )


# ---------- Public façade -----------------------------------------------------

class Classifier:
    """비전 분류기 파사드.

    state_machine 이 Classifier() (인자 없음) 로 생성하므로 cfg 미지정 시
    config.vision 을 내부에서 로드한다. 두 백엔드(YOLO/classical)와 더미 폴백이
    모두 ClassifyResult 계약을 공유한다.
    """

    def __init__(self, cfg: Optional[dict] = None) -> None:
        self._cfg = cfg if cfg is not None else config["vision"]
        self._dummy = bool(self._cfg.get("dummy_mode", False))
        self._impl = None
        self._mode = "dummy"

        if self._dummy:
            log.info("Classifier 더미 모드 (장비 없는 시연 안전판)")
            return

        mode = self._cfg.get("mode", "yolo")
        if mode == "yolo":
            try:
                self._impl = _YoloClassifier(self._resolve_model_path(self._cfg))
                self._mode = "yolo"
                return
            except Exception as e:
                log.warning(f"YOLO init 실패({e}) → classical/더미 폴백")

        if "mog2" in self._cfg and "classical" in self._cfg:
            self._impl = _ClassicalClassifier(self._cfg)
            self._mode = "classical"
        else:
            log.warning("classical 설정 없음 → 더미 폴백으로 동작")
            self._dummy = True
            self._mode = "dummy"

    @staticmethod
    def _resolve_model_path(cfg: dict) -> dict:
        """yolo_model_path 가 상대경로면 프로젝트 루트 기준으로 절대화."""
        p = cfg.get("yolo_model_path", "")
        path = Path(p)
        if not path.is_absolute():
            root = Path(__file__).resolve().parents[2]  # src/vision/ -> 루트
            path = root / p
        out = dict(cfg)
        out["yolo_model_path"] = str(path)
        return out

    @property
    def mode(self) -> str:
        return self._mode

    # ── ClassifyResult 반환 (원형 계약 보존) ──────────────────────────────
    def classify(self, frame) -> ClassifyResult:
        if self._dummy or self._impl is None:
            return self._dummy_result()
        if frame is None:
            return ClassifyResult(mode=self._mode)  # 미검출
        return self._impl.classify(frame)

    # ── 진단용: 모델이 뱉는 모든 박스 (불량 클래스 가려짐 확인) ───────────
    def raw_detections(self, frame) -> List[Dict[str, object]]:
        if self._mode == "yolo" and self._impl is not None and frame is not None:
            return self._impl.raw_detections(frame)  # type: ignore[attr-defined]
        return []

    # ── top 딕셔너리 어댑터 (염재니 Decision.evaluate top 입력) ───────────
    def classify_top(self, frame) -> dict:
        """비전 → Decision top 딕셔너리.

        반환: {"part","verdict_hint","confidence","raw_class"}
        part 는 영문(IC/Capacitor/Heatsink/TerminalBlock) 또는 None(미검출).
        """
        r = self.classify(frame)
        return {
            "part":           r.part,
            "verdict_hint":   r.verdict_hint,
            "confidence":     r.confidence,
            "raw_class":      r.raw_class,
            "defect_classes": r.defect_classes,   # 검출된 모든 불량 클래스(예: [Pinbent, Broken])
        }

    # ── 더미 폴백 (장비/카메라 없이 시연) ─────────────────────────────────
    def _dummy_result(self) -> ClassifyResult:
        part = random.choice(PARTS_EN)
        conf = round(random.uniform(0.85, 0.99), 2)
        if random.random() < _DUMMY_TOP_REJECT_RATE:
            raw = random.choice(["Broken", "Dented"])  # 상부 1차 불량 모사
            log.debug(f"[더미] 분류: {part} / REJECT({raw})")
            return ClassifyResult(part=part, verdict_hint="REJECT",
                                  confidence=conf, raw_class=raw, mode="dummy")
        log.debug(f"[더미] 분류: {part} / PASS")
        return ClassifyResult(part=part, verdict_hint="PASS",
                              confidence=conf, raw_class=part, mode="dummy")

    @staticmethod
    def vote(results: List[ClassifyResult]) -> ClassifyResult:
        """Stabilize over N consecutive frames. Majority vote on part, mean conf."""
        if not results:
            return ClassifyResult()
        counts: Dict[Optional[str], int] = {}
        for r in results:
            counts[r.part] = counts.get(r.part, 0) + 1
        winner = max(counts, key=counts.get)
        agreeing = [r for r in results if r.part == winner]
        # verdict_hint: REJECT wins if any frame says REJECT
        hint = "PASS"
        for r in agreeing:
            if r.verdict_hint == "REJECT":
                hint = "REJECT"
                break
            if r.verdict_hint == "UNKNOWN" and hint == "PASS":
                hint = "UNKNOWN"
        conf = sum(r.confidence for r in agreeing) / max(len(agreeing), 1)
        last = agreeing[-1]
        return ClassifyResult(
            part=winner, verdict_hint=hint, confidence=conf, bbox=last.bbox,
            features=last.features, raw_class=last.raw_class, mode=last.mode,
        )
