#!/bin/bash
# 현재 등록된 계정 확인 스크립트

echo "========================================="
echo "📋 등록된 계정 목록 (graphapi.db)"
echo "========================================="
sqlite3 ./data/graphapi.db <<EOF
.mode column
.headers on
SELECT
    id,
    user_id,
    email,
    status,
    is_active,
    auth_type,
    created_at,
    updated_at
FROM accounts
ORDER BY updated_at DESC;
EOF

echo ""
echo "========================================="
echo "🔐 DCR OAuth 토큰 (dcr_oauth.db)"
echo "========================================="
sqlite3 ./data/dcr_oauth.db <<EOF
.mode column
.headers on
SELECT
    object_id,
    user_email,
    user_name,
    application_id,
    expires_at,
    updated_at
FROM dcr_azure_tokens
ORDER BY updated_at DESC;
EOF

echo ""
echo "========================================="
echo "⚠️ 주의사항"
echo "========================================="
echo "1. 등록된 이메일과 다른 이메일로 로그인하면 에러가 발생합니다"
echo "2. user_id가 같으면 (이메일 @ 앞부분) 계정이 덮어써질 수 있습니다"
echo "3. DCR_ALLOWED_DOMAINS 환경변수로 허용된 도메인만 설정하세요"
echo ""
