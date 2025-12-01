#!/bin/bash

echo "==================================="
echo "Cloudflare 터널 설치"
echo "==================================="
echo ""
echo "Cloudflare 대시보드에서 복사한 설치 명령어를 붙여넣으세요:"
echo "(sudo cloudflared service install eyJ... 형태)"
echo ""
read -p "명령어 입력: " INSTALL_CMD

# 기존 서비스 중지
echo "🛑 기존 cloudflared 서비스 중지..."
sudo systemctl stop cloudflared 2>/dev/null
pkill cloudflared 2>/dev/null

# 명령어 실행
echo "📦 터널 설치 중..."
eval "$INSTALL_CMD"

echo ""
echo "✅ 터널 설치 완료!"
echo ""
echo "🔄 서비스 시작..."
sudo systemctl start cloudflared
sudo systemctl enable cloudflared

echo ""
echo "📊 서비스 상태:"
sudo systemctl status cloudflared --no-pager | head -15

echo ""
echo "==================================="
echo "다음 단계:"
echo "==================================="
echo "1. Cloudflare 대시보드로 돌아가세요"
echo "2. 상단의 'Hostname routes' 탭 클릭"
echo "3. 각 서비스별로 Public hostname 추가:"
echo "   - outlook.yourdomain.com → http://localhost:8001"
echo "   - teams.yourdomain.com → http://localhost:8003"
echo "   - onenote.yourdomain.com → http://localhost:8002"
echo "   - dashboard.yourdomain.com → http://localhost:8004"
echo "==================================="