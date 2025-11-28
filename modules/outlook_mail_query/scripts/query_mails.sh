#!/bin/bash

# 메일 조회 스크립트
# 모든 계정 또는 특정 계정의 메일을 조회합니다.
#
# 사용법:
#   ./query_mails.sh                          # 모든 계정 조회 (기본값: 최근 60일, 10개)
#   ./query_mails.sh kimghw                   # kimghw 계정만 조회
#   ./query_mails.sh kimghw 30 20             # kimghw 계정, 최근 30일, 최대 20개

# 스크립트 디렉토리 기준으로 프로젝트 루트 찾기
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Python 스크립트 경로
PYTHON_SCRIPT="$SCRIPT_DIR/query_mails.py"

cd "$PROJECT_ROOT"

# 인자에 따라 실행
if [ -z "$1" ]; then
    # 모든 계정 조회
    python3 "$PYTHON_SCRIPT"
elif [ -z "$2" ]; then
    # 특정 계정만 조회 (기본 설정)
    python3 "$PYTHON_SCRIPT" --user-id "$1"
elif [ -z "$3" ]; then
    # 특정 계정 + 기간 지정
    python3 "$PYTHON_SCRIPT" --user-id "$1" --days "$2"
else
    # 특정 계정 + 기간 + 최대 메일 수
    python3 "$PYTHON_SCRIPT" --user-id "$1" --days "$2" --max-mails "$3"
fi
