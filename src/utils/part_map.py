"""
부품명 매핑 단일 소스 (Single Source of Truth).

비전 이식(통합방향 A)에서 부품명이 세 가지 표현으로 존재한다:

    비전 출력(영문)   | DB enum(영문)     | 표시명/레시피(한글)
    -----------------|-------------------|--------------------
    IC               | IC_DIP14          | IC칩
    Capacitor        | CAP_220UF         | 커패시터
    TerminalBlock    | TERMINAL_BLOCK    | 터미널블록
    Heatsink         | HEATSINK_TO220    | 방열판

- 염재니 classifier 는 영문(part)을 반환한다.
- 김선진 RecipeManager.needs()/mark_collected(), TrayManager, WPF 표시, DB 는
  한글 부품명을 사용한다.
- 변환 로직을 여러 파일에 흩뿌리면 "config 2벌" 함정이 재발하므로,
  EN <-> KO <-> DB enum 변환은 **오직 이 파일에서만** 수행한다.

None(부품 미검출) 은 그대로 None 으로 통과시킨다 — 호출부에서 미검출을 구분할 수 있도록.
"""
from __future__ import annotations
from typing import Optional

# 비전 영문 → 한글 표시/레시피명 (정본)
_EN_TO_KO = {
    "IC":            "IC칩",
    "Capacitor":     "커패시터",
    "TerminalBlock": "터미널블록",
    "Heatsink":      "방열판",
}

# 비전 영문 → DB enum
_EN_TO_DB = {
    "IC":            "IC_DIP14",
    "Capacitor":     "CAP_220UF",
    "TerminalBlock": "TERMINAL_BLOCK",
    "Heatsink":      "HEATSINK_TO220",
}

# 역방향 (한글 → 영문) — 더미/역조회용
_KO_TO_EN = {v: k for k, v in _EN_TO_KO.items()}


def to_korean(part_en: Optional[str]) -> Optional[str]:
    """비전 영문 부품명 → 한글 표시/레시피명. 미검출(None)은 None 통과.

    recipe.needs()/mark_collected(), tray, DB, WPF 표시에 넘기기 전 반드시 거친다.
    매핑에 없는 미지 부품은 원문을 그대로 반환(로그 추적용).
    """
    if part_en is None:
        return None
    return _EN_TO_KO.get(part_en, part_en)


def to_db_enum(part_en: Optional[str]) -> Optional[str]:
    """비전 영문 부품명 → DB enum 문자열. 미검출(None)은 None 통과.

    현재 파이프라인은 표시 일관성을 위해 DB/MQTT 에 한글명을 저장한다.
    DB 를 영문 enum 으로 운용하려면 state_machine 의 payload 한 줄만
    to_korean → to_db_enum 으로 교체하면 된다(단일 지점 보장).
    """
    if part_en is None:
        return None
    return _EN_TO_DB.get(part_en, part_en)


def to_english(part_ko: Optional[str]) -> Optional[str]:
    """한글 부품명 → 비전 영문명 (역조회). 미지 입력은 원문 통과."""
    if part_ko is None:
        return None
    return _KO_TO_EN.get(part_ko, part_ko)


# 더미 모드(장비 없는 시연)에서 랜덤 선택에 쓸 영문 부품 목록 — 단일 소스 유지
PARTS_EN = list(_EN_TO_KO.keys())
