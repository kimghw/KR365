-- Teams 채팅 관련 스키마
-- Todo 요구사항:
-- - chat_id와 사용자 이름 매핑
-- - 최근 대화한 상대 및 대화 시간 기록
-- - 삭제된 대화방 이력 관리 (is_active 플래그)
-- - 대화 내용은 관리하지 않음 (Graph API에서 실시간 조회)

-- Teams 채팅방 정보 테이블
CREATE TABLE IF NOT EXISTS teams_chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,                      -- 사용자 ID (accounts.user_id와 연결)
    chat_id TEXT NOT NULL,                      -- Teams 채팅 ID (Graph API)
    chat_type TEXT NOT NULL,                    -- oneOnOne, group 등
    topic TEXT,                                 -- 채팅방 제목 (그룹 채팅인 경우)

    -- 멤버 정보
    member_count INTEGER DEFAULT 0,             -- 멤버 수
    members_json TEXT,                          -- 멤버 목록 (JSON)

    -- 1:1 채팅 상대방 정보 (oneOnOne인 경우)
    peer_user_name TEXT,                        -- 상대방 이름
    peer_user_email TEXT,                       -- 상대방 이메일

    -- 마지막 메시지 정보
    last_message_preview TEXT,                  -- 마지막 메시지 미리보기
    last_message_time TIMESTAMP,                -- 마지막 메시지 시간 (Graph API)

    -- 사용자 액션 추적
    last_sent_at TIMESTAMP,                     -- 마지막 메시지 전송 시간 (우리가 보낸 메시지)
    last_received_at TIMESTAMP,                 -- 마지막 메시지 수신 시간 (받은 메시지)

    -- 메타데이터
    is_active BOOLEAN NOT NULL DEFAULT TRUE,    -- 활성 상태 (삭제된 대화방은 FALSE)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_sync_at TIMESTAMP,                     -- 마지막 동기화 시간

    -- 복합 유니크 제약 (user_id + chat_id)
    UNIQUE(user_id, chat_id)
);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_teams_chats_user_id ON teams_chats (user_id);
CREATE INDEX IF NOT EXISTS idx_teams_chats_chat_id ON teams_chats (chat_id);
CREATE INDEX IF NOT EXISTS idx_teams_chats_peer_name ON teams_chats (peer_user_name);
CREATE INDEX IF NOT EXISTS idx_teams_chats_is_active ON teams_chats (is_active);

-- 최근 대화 조회 성능 최적화 인덱스
-- last_sent_at, last_received_at, last_message_time 순으로 최근 대화 판단
CREATE INDEX IF NOT EXISTS idx_teams_chats_recent_activity
    ON teams_chats (user_id, is_active, last_sent_at DESC, last_received_at DESC, last_message_time DESC);

-- 사용자 이름 검색 성능 최적화 (LOWER() 함수 사용)
CREATE INDEX IF NOT EXISTS idx_teams_chats_peer_name_lower
    ON teams_chats (user_id, is_active, LOWER(peer_user_name));

CREATE INDEX IF NOT EXISTS idx_teams_chats_topic_lower
    ON teams_chats (user_id, is_active, LOWER(topic));

-- accounts 테이블 (Teams 전용 DB 사용 시)
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL UNIQUE,
    email TEXT UNIQUE,
    display_name TEXT,
    azure_object_id TEXT,
    oauth_tenant_id TEXT,
    oauth_client_id TEXT,
    oauth_redirect_uri TEXT,
    oauth_client_secret TEXT,
    delegated_permissions TEXT,
    access_token TEXT,
    refresh_token TEXT,
    token_expiry DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- accounts 테이블 인덱스
CREATE INDEX IF NOT EXISTS idx_accounts_email ON accounts(email);
CREATE INDEX IF NOT EXISTS idx_accounts_azure_object_id ON accounts(azure_object_id);
