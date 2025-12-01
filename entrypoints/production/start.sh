#!/bin/bash

# Unified Server 시작 스크립트

# 기본 포트 설정
export UNIFIED_PORT=${UNIFIED_PORT:-8080}
export UNIFIED_HOST=${UNIFIED_HOST:-0.0.0.0}

echo "🚀 Starting KR365 Unified Server..."
echo "📍 Host: $UNIFIED_HOST"
echo "🔌 Port: $UNIFIED_PORT"

# Python 경로 설정
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

# 서버 실행
cd "$PROJECT_ROOT"
python entrypoints/production/unified_server.py