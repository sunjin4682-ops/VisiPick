# 비전 이식 노트 (염재니 비전 → 김선진 몸통, 통합방향 A)

> 인프라(api_server, db, agv_mqtt, serial_ctrl, robot, mqtt 토픽, camera_top/side,
> recipe_mgr, tray_mgr, state_machine 골격)는 **김선진 것 그대로**. 비전 경계만 교체.

## 이식한 파일 (딱 3개 + 어댑터 2개)

| 파일 | 동작 | 출처 |
|------|------|------|
| `src/vision/classifier.py` | 교체 | 염재니 classifier.py (YOLO+classical) + 파사드/어댑터 |
| `src/vision/pin_inspector.py` | 신규 | 염재니 pin_inspector.py + 파사드/어댑터 |
| `src/orchestrator/decision.py` | 교체 | 염재니 Decision + 라벨/결함 매핑, gate_action_for 유지 |
| `src/utils/part_map.py` | 신규 | 부품명 EN/KO/DB 단일 변환 지점 |
| `src/core/state_machine.py` | 최소수정 | `_inspect_one` 데이터 흐름만 B구조로 |
| `config/config.json` | 병합 | vision + pin_inspector 키 |
| `models/best.pt` | 추가 | 염재니 YOLO 가중치 (7-class) |

염재니 `main.py / pipeline.py / api.py / io_drivers / camera.py / recipe_mgr / tray_mgr`
는 **이식하지 않음**. 김선진 인프라 사용.

## 데이터 흐름 (state_machine `_inspect_one`)

```
frame_top  = cam_top.capture()
frame_side = cam_side.capture()
top  = clf.classify_top(frame_top)             # {part(EN|None), verdict_hint, confidence, raw_class}
side = pin.inspect_side(frame_side, top.part)  # {verdict, pin_count, gap_cv, tip_y_range_px}
result = Decision.evaluate(top, side)          # 염재니 채택, judge 폐기
cls    = verdict_to_label(result.verdict)      # PASS→NEEDED, REJECT→DEFECT, DUPLICATE→DUPLICATE
defect = defect_code_for(result, top, side)    # NONE|BENT_PIN|BROKEN|UNKNOWN
part_ko= to_korean(top.part)                   # 영문 → 한글 (표시/레시피/DB) — 단일 지점
action = gate_action_for(cls)                  # 김선진 게이트 매핑 그대로
```

## 실제 업로드 파일 확인으로 잡은 함정 4가지 (추측 금지)

1. **best.pt 는 3-class 가 아니라 7-class 다.**
   `data.yaml`(=epoch*.pt 용)은 `['CAP','HS','IC']` 지만, 실제 `best.pt.names`
   = `{0:Broken,1:CAP,2:Dented,3:HS,4:IC,5:Pinbent,6:TB}` (config.yolo_class_index 와 일치).

2. **classifier 는 FLAT class_map 을 읽는데 염재니 config 는 NESTED 였다.**
   classifier 코드: `class_map.get(cls_name) -> {"part","verdict"}`.
   염재니 config.json: `yolo_class_map = {parts:{...}, defects:{...}}` (중첩).
   → 그대로 합치면 **모든 부품이 part=None → 전량 REJECT**. ("config 2벌" 함정)
   → 병합 config 는 코드가 읽는 **FLAT 형태**로 제공:
   ```
   "IC":{"part":"IC","verdict":"PASS"} ... "Broken":{"verdict":"REJECT"} ...
   ```

3. **pin_inspector config 키는 프롬프트 추정명이 아니라 코드가 읽는 실제 키.**
   프롬프트 추정: `expected / gap_cv_tolerance / roi_bottom_ratio` (코드에 없음).
   실제 코드: `canny_low, canny_high, blur_ksize, expected_pin_count,
   pin_gap_tolerance_pct, tip_y_tolerance_px` (roi 비율은 0.55 하드코딩).
   → config 는 **실제 키**로 작성.

4. **is_duplicate 부호 + 부품명 언어가 둘 다 반대.**
   Decision: `is_duplicate(part)=True → 중복`. 김선진 `needs(part)=True → 아직 필요`(반대).
   게다가 비전 part 는 영문, `needs()` 는 한글.
   → `is_duplicate = lambda p: (p is not None) and (not recipe.needs(to_korean(p)))`

## DB/표시 부품명 = 한글 (영문 enum 은 part_map 에 준비만)

`RecipeManager.needs()/mark_collected()`, `TrayManager`, DB `PartType`, WPF 표시,
`get_stats()` 집계가 모두 한글명을 사용한다. 일관성을 위해 payload `part_type` 는
`to_korean()` 한글로 저장/발행한다. `to_db_enum()`(IC→IC_DIP14 등)은 part_map 에
단일 정의해 두었고, DB 를 영문 enum 으로 운용하려면 `_inspect_one` payload 한 줄
(`to_korean` → `to_db_enum`)만 바꾸면 된다(흩뿌리지 않음).

## V7.2 보존 키 (현재 미사용)

`yolo_class_index`, `defect_iou_threshold`, `defect_min_conf` 는 결함박스를 부품박스와
IoU 로 연계하는 향후 분류기를 위한 키다. **현 염재니 분류기는 top-1 박스만** 사용하므로
읽지 않는다(이식 범위 밖). 결함은 ① 상부 결함클래스(Broken/Dented/Pinbent)가 top-1 일 때,
② 측면 핀검사 BENT 일 때 잡힌다(2-카메라 안전망). 보존해 두어 실장 전환 시 KeyError 없음.

## 더미 폴백 (장비 없는 50회 시연 안전판)

`config.vision.dummy_mode = true` (기본값) → Classifier/PinInspector 가 모델을
로드하지 않고 랜덤 결과를 낸다. `frame=None` 이어도 죽지 않음. Decision 은 더미에서도
**실제 로직 그대로** 돈다.

## 실장(YOLO 라이브) 전환 — 한 줄

```jsonc
// config/config.json
"vision": { "dummy_mode": false, ... }   // 카메라 연결(top index 0 / side index 1) 필요
```
`dummy_mode=false` 면 `models/best.pt` 로드 후 실제 추론. 카메라가 없으면 김선진
camera_top/side 가 RuntimeError 를 낸다(설계 그대로) → 시연은 dummy_mode=true 권장.

## 자가검증

```
cd C:\Final_Project\VisiPick
python tests/test_vision_integration.py      # 47/47 PASS (더미 + 실제 YOLO)
```
- 실제 best.pt 추론: 결함 크롭 → DEFECT, 컨베이어 프레임(Heatsink) → NEEDED → DUPLICATE.

## 추가 의존성

`loguru==0.7.3` (requirements.txt 기재, 본 환경에 설치 완료).
YOLO 실행: `ultralytics`, `torch`, `opencv-python` (설치 완료).
