#!/usr/bin/env bash
# VisiPick SQLite 백업 (Jetson/Linux) — backup.ps1의 bash 포팅
# scripts/ 아래에 overlay된 상태로 실행한다고 가정한다.
# 스크립트 위치 기준으로 프로젝트 루트를 계산하므로 clone 경로가 달라도 동작한다.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

DATE="$(date +%Y-%m-%d)"
SRC="$ROOT_DIR/data/visipick.db"
DEST_DIR="$ROOT_DIR/backup"
DEST="$DEST_DIR/visipick-$DATE.db"

if [[ ! -f "$SRC" ]]; then
  echo "백업 대상 DB 없음: $SRC" >&2
  exit 1
fi

mkdir -p "$DEST_DIR"

# WAL 모드 안전 백업: sqlite3가 있으면 .backup 사용(잠금 안전), 없으면 파일 복사 폴백
if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$SRC" ".backup '$DEST'"
else
  cp "$SRC" "$DEST"
fi

echo "백업 완료: $DEST"
