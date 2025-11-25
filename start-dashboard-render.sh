#!/bin/bash
# OnRender용 Dashboard Server Launcher
# OnRender 환경에 최적화된 설정

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# OnRender에서는 PORT 환경변수가 자동 설정됨
PORT=${PORT:-10000}
HOST="0.0.0.0"  # OnRender는 0.0.0.0 필요

# 절대 경로로 변환
export DATABASE_PATH="$SCRIPT_DIR/data/graphapi.db"
export DCR_DATABASE_PATH="$SCRIPT_DIR/data/dcr.db"

# 디렉토리 생성 (환경변수의 경로에서 디렉토리 추출)
DB_DIR=$(dirname "$DATABASE_PATH")
DCR_DB_DIR=$(dirname "$DCR_DATABASE_PATH")

mkdir -p "$DB_DIR"
mkdir -p "$DCR_DB_DIR"
mkdir -p logs

# 환경 변수 확인
echo "🔍 Environment Check:"
echo "  PORT: $PORT"
echo "  DATABASE_PATH: $DATABASE_PATH"
echo "  DCR_DATABASE_PATH: $DCR_DATABASE_PATH"
echo "  DATA_DIR: $DATA_DIR"
echo "  LOG_DIR: $LOG_DIR"
echo "  DASHBOARD_ADMIN_USERNAME: ${DASHBOARD_ADMIN_USERNAME:+[SET]}"
echo "  DASHBOARD_ADMIN_PASSWORD: ${DASHBOARD_ADMIN_PASSWORD:+[SET]}"
echo ""

# DB 파일 존재 여부 확인
if [ -f "$DATABASE_PATH" ]; then
    echo "✅ Main database exists: $DATABASE_PATH"
    echo "   Size: $(ls -lh "$DATABASE_PATH" | awk '{print $5}')"
    echo "   Modified: $(ls -l "$DATABASE_PATH" | awk '{print $6, $7, $8}')"
else
    echo "⚠️  Main database not found, will be created at: $DATABASE_PATH"
fi

if [ -f "$DCR_DATABASE_PATH" ]; then
    echo "✅ DCR database exists: $DCR_DATABASE_PATH"
    echo "   Size: $(ls -lh "$DCR_DATABASE_PATH" | awk '{print $5}')"
    echo "   Modified: $(ls -l "$DCR_DATABASE_PATH" | awk '{print $6, $7, $8}')"
else
    echo "⚠️  DCR database not found, will be created at: $DCR_DATABASE_PATH"
fi

# 디렉토리 권한 확인
echo ""
echo "📂 Directory permissions:"
ls -ld "$DATA_DIR" 2>/dev/null || echo "   DATA_DIR: Not accessible"
ls -ld "$LOG_DIR" 2>/dev/null || echo "   LOG_DIR: Not accessible"

echo ""
echo "🔍 Debug Information:"
echo "  Current Directory: $(pwd)"
echo "  Python Path: $(which python3)"
echo "  Python Version: $(python3 --version)"
echo ""

# Python에서 config 값 확인
echo "📊 Testing database connection..."
python3 -c "
import sys
import os
sys.path.insert(0, '.')
from infra.core.config import get_config
config = get_config()
print(f'  Database Path from Config: {config.database_path}')
print(f'  DCR Database Path from Config: {config.dcr_database_path}')
print(f'  Encryption Key Set: {bool(config.encryption_key)}')
" || echo "  ⚠️ Config loading failed"

echo ""
echo "🚀 Starting Dashboard Server on port $PORT..."

# OnRender는 백그라운드 실행 불필요 (직접 실행)
exec python3 modules/web_dashboard/standalone_server.py --host $HOST --port $PORT