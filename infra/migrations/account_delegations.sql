-- 계정 권한 위임 테이블
-- 특정 사용자가 다른 사용자의 데이터를 조회할 수 있도록 권한을 부여

CREATE TABLE IF NOT EXISTS account_delegations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 권한 관계
    delegator_user_id TEXT NOT NULL,      -- 데이터 소유자 (권한을 주는 사람)
    delegate_user_id TEXT NOT NULL,        -- 접근자 (권한을 받는 사람)

    -- 참고 정보
    delegator_email TEXT,                  -- 소유자 이메일 (참고용)
    delegate_email TEXT,                   -- 접근자 이메일 (참고용)

    -- 권한 설정
    permissions TEXT DEFAULT 'read',       -- read, read_write

    -- 시간 정보
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME,                   -- 만료 시간 (NULL = 무제한)

    -- 상태
    is_active BOOLEAN DEFAULT 1,

    -- 제약 조건
    UNIQUE(delegator_user_id, delegate_user_id),
    FOREIGN KEY (delegator_user_id) REFERENCES accounts(user_id) ON DELETE CASCADE,
    FOREIGN KEY (delegate_user_id) REFERENCES accounts(user_id) ON DELETE CASCADE
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_delegations_delegate
ON account_delegations(delegate_user_id, is_active, expires_at);

CREATE INDEX IF NOT EXISTS idx_delegations_delegator
ON account_delegations(delegator_user_id, is_active);

-- 관리자 플래그 추가
ALTER TABLE accounts ADD COLUMN is_admin BOOLEAN DEFAULT 0;

-- 관리자 인덱스
CREATE INDEX IF NOT EXISTS idx_accounts_admin ON accounts(is_admin) WHERE is_admin = 1;
