#!/bin/bash

# Colors for better readability
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Tunnel ID (현재 설정된 터널)
TUNNEL_ID="4363796e-94e3-4d17-a060-f68469df8969"

function show_menu() {
    clear
    echo -e "${BLUE}============================================${NC}"
    echo -e "${BLUE}     Cloudflare Tunnel Management Menu     ${NC}"
    echo -e "${BLUE}============================================${NC}"
    echo -e "${GREEN}터널 ID: ${TUNNEL_ID}${NC}"
    echo ""
    echo "1) 서비스 상태 확인"
    echo "2) 서비스 시작"
    echo "3) 서비스 정지"
    echo "4) 서비스 재시작"
    echo "5) 실시간 로그 보기"
    echo "6) 최근 로그 확인 (50줄)"
    echo "7) 터널 정보 확인"
    echo "8) 터널 목록 보기"
    echo "9) 원격 로그 스트리밍"
    echo "10) 버전 확인"
    echo "11) 서비스 재설치"
    echo "12) 서비스 제거"
    echo "13) 도메인 연결 테스트"
    echo "0) 종료"
    echo ""
}

function check_status() {
    echo -e "${YELLOW}서비스 상태 확인 중...${NC}"
    sudo systemctl status cloudflared --no-pager
    echo ""
    read -p "Enter를 눌러 계속..."
}

function start_service() {
    echo -e "${YELLOW}서비스 시작 중...${NC}"
    sudo systemctl start cloudflared
    sleep 2
    sudo systemctl status cloudflared --no-pager | head -10
    echo ""
    read -p "Enter를 눌러 계속..."
}

function stop_service() {
    echo -e "${YELLOW}서비스 정지 중...${NC}"
    sudo systemctl stop cloudflared
    echo -e "${GREEN}서비스가 정지되었습니다.${NC}"
    echo ""
    read -p "Enter를 눌러 계속..."
}

function restart_service() {
    echo -e "${YELLOW}서비스 재시작 중...${NC}"
    sudo systemctl restart cloudflared
    sleep 2
    sudo systemctl status cloudflared --no-pager | head -10
    echo ""
    read -p "Enter를 눌러 계속..."
}

function show_live_logs() {
    echo -e "${YELLOW}실시간 로그 (Ctrl+C로 종료)${NC}"
    echo ""
    sudo journalctl -u cloudflared -f
}

function show_recent_logs() {
    echo -e "${YELLOW}최근 로그 50줄${NC}"
    echo ""
    sudo journalctl -u cloudflared -n 50 --no-pager
    echo ""
    read -p "Enter를 눌러 계속..."
}

function tunnel_info() {
    echo -e "${YELLOW}터널 정보${NC}"
    echo ""
    cloudflared tunnel info ${TUNNEL_ID} 2>&1 || echo "터널 정보를 가져올 수 없습니다. (토큰 모드에서는 제한적)"
    echo ""
    read -p "Enter를 눌러 계속..."
}

function tunnel_list() {
    echo -e "${YELLOW}터널 목록${NC}"
    echo ""
    cloudflared tunnel list 2>&1 || echo "터널 목록을 가져올 수 없습니다. (토큰 모드에서는 제한적)"
    echo ""
    read -p "Enter를 눌러 계속..."
}

function tail_logs() {
    echo -e "${YELLOW}원격 로그 스트리밍 (Ctrl+C로 종료)${NC}"
    echo ""
    cloudflared tail ${TUNNEL_ID} 2>&1 || echo "원격 로그를 가져올 수 없습니다."
}

function check_version() {
    echo -e "${YELLOW}Cloudflared 버전 정보${NC}"
    echo ""
    cloudflared version
    echo ""
    read -p "Enter를 눌러 계속..."
}

function reinstall_service() {
    echo -e "${YELLOW}서비스 재설치${NC}"
    echo ""
    echo "Cloudflare 대시보드에서 토큰을 복사해주세요:"
    echo "1. https://one.dash.cloudflare.com 접속"
    echo "2. Zero Trust → Access → Tunnels"
    echo "3. 터널 선택 → Configure → Install connector"
    echo ""
    read -p "토큰 입력 (eyJ...): " TOKEN

    if [ -n "$TOKEN" ]; then
        sudo cloudflared service uninstall
        sudo cloudflared service install $TOKEN
        echo -e "${GREEN}서비스가 재설치되었습니다.${NC}"
    else
        echo -e "${RED}토큰이 입력되지 않았습니다.${NC}"
    fi
    echo ""
    read -p "Enter를 눌러 계속..."
}

function uninstall_service() {
    echo -e "${RED}서비스 제거${NC}"
    echo ""
    read -p "정말로 서비스를 제거하시겠습니까? (y/N): " confirm

    if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
        sudo systemctl stop cloudflared
        sudo cloudflared service uninstall
        echo -e "${GREEN}서비스가 제거되었습니다.${NC}"
    else
        echo "취소되었습니다."
    fi
    echo ""
    read -p "Enter를 눌러 계속..."
}

function test_domains() {
    echo -e "${YELLOW}도메인 연결 테스트${NC}"
    echo ""

    # 설정된 도메인 목록
    domains=(
        "outlook.kimghw.org:8001"
        "teams.kimghw.org:8003"
        "onenote.kimghw.org:8002"
        "dashboard.kimghw.org:8004"
    )

    for domain_port in "${domains[@]}"; do
        domain="${domain_port%:*}"
        port="${domain_port#*:}"

        # HTTP 상태 확인
        status=$(curl -s -o /dev/null -w "%{http_code}" https://$domain 2>/dev/null)

        # 로컬 포트 확인
        if netstat -tln 2>/dev/null | grep -q ":$port "; then
            local_status="${GREEN}실행중${NC}"
        else
            local_status="${RED}미실행${NC}"
        fi

        # 상태에 따른 색상
        if [ "$status" = "200" ]; then
            status_color="${GREEN}$status${NC}"
        elif [ "$status" = "502" ] || [ "$status" = "530" ]; then
            status_color="${YELLOW}$status${NC}"
        else
            status_color="${RED}$status${NC}"
        fi

        printf "%-25s HTTP: %s  로컬서비스(:%s): %s\n" "$domain" "$status_color" "$port" "$local_status"
    done

    echo ""
    echo "HTTP 상태 코드:"
    echo "  200 - 정상"
    echo "  502 - Bad Gateway (서비스 미실행)"
    echo "  530 - Origin 연결 실패"
    echo "  000 - DNS 미설정 또는 연결 불가"
    echo ""
    read -p "Enter를 눌러 계속..."
}

# Main loop
while true; do
    show_menu
    read -p "선택: " choice

    case $choice in
        1) check_status ;;
        2) start_service ;;
        3) stop_service ;;
        4) restart_service ;;
        5) show_live_logs ;;
        6) show_recent_logs ;;
        7) tunnel_info ;;
        8) tunnel_list ;;
        9) tail_logs ;;
        10) check_version ;;
        11) reinstall_service ;;
        12) uninstall_service ;;
        13) test_domains ;;
        0)
            echo "종료합니다."
            exit 0
            ;;
        *)
            echo -e "${RED}잘못된 선택입니다. 다시 시도하세요.${NC}"
            sleep 2
            ;;
    esac
done