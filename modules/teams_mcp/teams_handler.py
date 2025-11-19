"""
Teams Graph API Handler
Microsoft Graph API를 사용한 Teams 작업 처리 (통합 핸들러)
"""

from typing import Optional, Dict, Any, List
from infra.core.logger import get_logger
from infra.core.token_service import TokenService

# 서브 모듈 import
from .teams_db_manager import TeamsDBManager
from .teams_chats import TeamsChats
from .teams_messages import TeamsMessages
from .teams_search import TeamsSearch

logger = get_logger(__name__)

# 특별한 Teams Chat ID 상수
# 주의: 이 chat_id들은 teams_list_chats API에 나타나지 않지만 직접 사용 가능합니다
SPECIAL_CHAT_IDS = {
    "notes": "48:notes",  # Teams Notes 채팅 (개인 메모용)
}


class TeamsHandler:
    """Teams Graph API 작업 처리 핸들러 (메인)"""

    def __init__(self):
        self.token_service = TokenService()
        self.graph_base_url = "https://graph.microsoft.com/v1.0"

        # 서브 모듈 초기화
        self.db_manager = TeamsDBManager()
        self.chats_manager = TeamsChats(self.graph_base_url)
        self.messages_manager = TeamsMessages(self.graph_base_url)
        self.search_manager = TeamsSearch(self.graph_base_url)

    async def _resolve_chat_id(
        self,
        user_id: str,
        chat_id: Optional[str] = None,
        recipient_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        chat_id 결정 로직(이름 검색 포함). 필요 시 DB 동기화(단일 채팅 UPSERT).

        우선순위:
        1) 입력 chat_id
        2) recipient_name → DB 조회
        3) recipient_name → Graph에서 멤버 검색 후 DB UPSERT
        4) Notes 기본값(48:notes) - chat_id와 recipient_name 둘 다 없으면 무조건 Notes
        """
        try:
            if chat_id:
                return chat_id

            # 이름 기반: DB 먼저
            if recipient_name:
                found = await self.db_manager.find_chat_by_name(user_id, recipient_name)
                if found:
                    return found

                # DB에 없으면 Graph에서 조회 후 멤버 검색
                access_token = await self._get_access_token(user_id)
                if not access_token:
                    return None

                chats_result = await self.chats_manager.list_chats(access_token)
                if not chats_result.get("success"):
                    return None

                chats = chats_result.get("chats", [])
                needle = (recipient_name or "").lower()

                # topic에서 먼저 매칭 시도
                for c in chats:
                    topic_val = (c.get("topic") or "").lower()
                    if needle and needle in topic_val:
                        # DB에 단일 UPSERT
                        await self.db_manager.upsert_chat(user_id, c, [])
                        return c.get("id")

                # 멤버 목록을 조회하며 매칭
                for c in chats:
                    cid = c.get("id")
                    members_result = await self.chats_manager.get_chat_members(access_token, cid)
                    if not members_result.get("success"):
                        continue
                    members = members_result.get("members", [])
                    matched = False
                    for m in members:
                        display_name = (m.get("displayName") or "").lower()
                        email = (m.get("email") or m.get("mail") or m.get("userPrincipalName") or "").lower()
                        if needle in display_name or (email and needle in email):
                            matched = True
                            break
                    if matched:
                        # DB에 단일 UPSERT(멤버 포함)
                        await self.db_manager.upsert_chat(user_id, c, members)
                        return cid

            # chat_id와 recipient_name 둘 다 없으면 무조건 Notes(48:notes)
            logger.info("ℹ️ chat_id/recipient_name 없음, 기본값 48:notes 사용")
            return "48:notes"

        except Exception as e:
            logger.error(f"❌ chat_id 결정 오류: {str(e)}", exc_info=True)
            return None

    async def _get_access_token(self, user_id: str) -> Optional[str]:
        """
        사용자 ID로 유효한 액세스 토큰 조회 (자동 갱신 포함)

        Args:
            user_id: 사용자 ID

        Returns:
            유효한 액세스 토큰 또는 None
        """
        try:
            # TokenService를 사용하여 토큰 유효성 확인 및 자동 갱신
            return await self.token_service.get_valid_access_token(user_id)
        except Exception as e:
            logger.error(f"❌ 토큰 조회 실패: {str(e)}")
            return None

    # ========================================================================
    # 채팅 목록 관련
    # ========================================================================

    async def list_chats(
        self,
        user_id: str,
        sort_by: str = "recent",
        limit: Optional[int] = None,
        filter_by_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        사용자의 채팅 목록 조회 (1:1 및 그룹 채팅)

        Args:
            user_id: 사용자 ID
            sort_by: 정렬 방식 ("recent", "name", "type") - 기본값: "recent"
            limit: 최대 조회 개수 (None이면 전체)
            filter_by_name: 이름 필터 (Optional)

        Returns:
            채팅 목록 (최근 대화 5개 + 전체 목록)
        """
        try:
            access_token = await self._get_access_token(user_id)
            if not access_token:
                return {"success": False, "message": "액세스 토큰이 없습니다"}

            # 채팅 목록 조회
            result = await self.chats_manager.list_chats(
                access_token, sort_by, limit, filter_by_name
            )

            # 성공 시 DB 동기화
            if result.get("success") and result.get("chats"):
                await self.db_manager.sync_chats_to_db(user_id, result["chats"])

                # DB에서 한글/상대 이름을 가져와 각 채팅에 주입
                chats = result["chats"]
                for chat in chats:
                    chat_id = chat.get("id")
                    if chat_id:
                        db_result = self.db_manager.db.execute_query(
                            "SELECT topic_kr, peer_user_name, peer_user_email FROM teams_chats WHERE user_id = ? AND chat_id = ?",
                            (user_id, chat_id),
                            fetch_result=True
                        )
                        if db_result and len(db_result) > 0:
                            topic_kr_val, peer_name_val, peer_email_val = db_result[0]
                            if topic_kr_val:
                                chat["topic_kr"] = topic_kr_val
                            if peer_name_val:
                                chat["peer_user_name"] = peer_name_val
                            if peer_email_val:
                                chat["peer_user_email"] = peer_email_val

                # DB에서 최근 대화 5개 조회 (topic + 시간)
                recent_chats_result = self.db_manager.db.execute_query(
                    """
                    SELECT
                        chat_id,
                        COALESCE(topic_kr, topic, peer_user_name) as display_name,
                        CASE
                            WHEN last_sent_at IS NOT NULL THEN last_sent_at
                            WHEN last_received_at IS NOT NULL THEN last_received_at
                            WHEN last_message_time IS NOT NULL THEN last_message_time
                            ELSE created_at
                        END as recent_time
                    FROM teams_chats
                    WHERE user_id = ? AND is_active = TRUE
                    ORDER BY recent_time DESC
                    LIMIT 5
                    """,
                    (user_id,),
                    fetch_result=True
                )

                recent_chats = []
                if recent_chats_result:
                    for row in recent_chats_result:
                        recent_chats.append({
                            "chat_id": row[0],
                            "topic": row[1],
                            "last_activity": row[2]
                        })

                result["recent_chats"] = recent_chats

            return result

        except Exception as e:
            logger.error(f"❌ 채팅 목록 조회 오류: {str(e)}", exc_info=True)
            return {"success": False, "message": f"오류 발생: {str(e)}"}

    # ========================================================================
    # 메시지 조회/전송
    # ========================================================================

    async def get_chat_messages(
        self,
        user_id: str,
        chat_id: Optional[str] = None,
        recipient_name: Optional[str] = None,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        채팅의 메시지 목록 조회

        Args:
            user_id: 사용자 ID
            chat_id: 채팅 ID (Optional)
            recipient_name: 상대방 이름 (chat_id가 없을 때 사용)
            limit: 조회할 메시지 수 (기본 50)

        Returns:
            메시지 목록
        """
        try:
            # chat_id 결정 (이름 검색 포함)
            chat_id = await self._resolve_chat_id(user_id, chat_id, recipient_name)
            if not chat_id:
                return {"success": False, "message": "chat_id를 결정할 수 없습니다"}

            access_token = await self._get_access_token(user_id)
            if not access_token:
                return {"success": False, "message": "액세스 토큰이 없습니다"}

            return await self.messages_manager.get_chat_messages(access_token, chat_id, limit)

        except Exception as e:
            logger.error(f"❌ 메시지 조회 오류: {str(e)}", exc_info=True)
            return {"success": False, "message": f"오류 발생: {str(e)}"}

    async def send_chat_message(
        self,
        user_id: str,
        content: str,
        chat_id: Optional[str] = None,
        recipient_name: Optional[str] = None,
        prefix: str = "[claude]"
    ) -> Dict[str, Any]:
        """
        채팅에 메시지 전송

        Args:
            user_id: 사용자 ID
            content: 메시지 내용
            chat_id: 채팅 ID (Optional)
            recipient_name: 상대방 이름 (chat_id가 없을 때 사용)
            prefix: 메시지 앞에 붙을 프리픽스 (기본값: '[claude]')

        Returns:
            전송 결과
        """
        try:
            # chat_id 결정 (이름 검색 포함)
            chat_id = await self._resolve_chat_id(user_id, chat_id, recipient_name)
            if not chat_id:
                return {"success": False, "message": "chat_id를 결정할 수 없습니다"}

            access_token = await self._get_access_token(user_id)
            if not access_token:
                return {"success": False, "message": "액세스 토큰이 없습니다"}

            # 메시지 전송
            result = await self.messages_manager.send_chat_message(
                access_token, chat_id, content, prefix
            )

            # 성공 시 DB 업데이트
            if result.get("success"):
                await self.db_manager.update_last_sent_at(user_id, chat_id)

            return result

        except Exception as e:
            logger.error(f"❌ 메시지 전송 오류: {str(e)}", exc_info=True)
            return {"success": False, "message": f"오류 발생: {str(e)}"}

    # ========================================================================
    # 메시지 검색
    # ========================================================================

    async def search_messages(
        self,
        user_id: str,
        keyword: str,
        search_scope: str = "current_chat",
        chat_id: Optional[str] = None,
        page_size: int = 50,
        max_results: int = 500
    ) -> Dict[str, Any]:
        """
        메시지 키워드 검색

        Args:
            user_id: 사용자 ID
            keyword: 검색 키워드
            search_scope: 검색 범위 ("current_chat" 또는 "all_chats")
            chat_id: 채팅 ID (search_scope="current_chat"일 때 필수)
            page_size: 페이지 크기 (기본 50)
            max_results: 최대 결과 수 (기본 500)

        Returns:
            검색 결과
        """
        try:
            access_token = await self._get_access_token(user_id)
            if not access_token:
                return {"success": False, "message": "액세스 토큰이 없습니다"}

            return await self.search_manager.search_messages(
                access_token, keyword, search_scope, chat_id, page_size, max_results
            )

        except Exception as e:
            logger.error(f"❌ 메시지 검색 오류: {str(e)}", exc_info=True)
            return {"success": False, "message": f"오류 발생: {str(e)}"}

    # ========================================================================
    # 한글 이름 저장
    # ========================================================================

    async def save_korean_name(
        self,
        user_id: str,
        topic_kr: str,
        chat_id: Optional[str] = None,
        topic_en: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        채팅의 한글 이름을 저장

        Args:
            user_id: 사용자 ID
            topic_kr: 한글 이름
            chat_id: 채팅 ID (선택)
            topic_en: 영문 이름 (선택, chat_id가 없을 때 검색용)

        Returns:
            저장 결과
        """
        try:
            return await self.db_manager.save_korean_name(user_id, chat_id, topic_en, topic_kr)

        except Exception as e:
            logger.error(f"❌ 한글 이름 저장 오류: {str(e)}", exc_info=True)
            return {"success": False, "message": f"오류 발생: {str(e)}"}

    async def save_korean_names_batch(
        self,
        user_id: str,
        names: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        여러 채팅의 한글 이름을 한 번에 저장

        Args:
            user_id: 사용자 ID
            names: [{"topic_en": "영문", "topic_kr": "한글"}, ...] 형식의 리스트

        Returns:
            배치 저장 결과
        """
        try:
            return await self.db_manager.save_korean_names_batch(user_id, names)

        except Exception as e:
            logger.error(f"❌ 배치 저장 오류: {str(e)}", exc_info=True)
            return {"success": False, "message": f"오류 발생: {str(e)}"}

    # ========================================================================
    # 날짜별 채팅 조회
    # ========================================================================

    async def get_chats_by_date(
        self,
        user_id: str,
        days: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        user_name_filter: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        날짜 범위 내에서 활동이 있었던 채팅방 조회 (lastModifiedDateTime 기준)

        Args:
            user_id: 사용자 ID
            days: 조회할 일수 (기본 7일)
            start_date: 시작 날짜 (ISO 8601 형식)
            end_date: 종료 날짜 (ISO 8601 형식)
            user_name_filter: 특정 사용자 이름으로 필터링 (선택)

        Returns:
            날짜 범위 내 채팅 목록 (사용자별 정리)
        """
        try:
            access_token = await self._get_access_token(user_id)
            if not access_token:
                return {"success": False, "message": "액세스 토큰이 없습니다"}

            # 날짜별 채팅 조회
            result = await self.chats_manager.get_chats_by_date_range(
                access_token, days, start_date, end_date
            )

            if not result.get("success"):
                return result

            chats = result.get("chats", [])

            # DB 동기화
            if chats:
                await self.db_manager.sync_chats_to_db(user_id, chats)

                # DB에서 한글/상대 이름을 가져와 각 채팅에 주입
                for chat in chats:
                    chat_id = chat.get("id")
                    if chat_id:
                        db_result = self.db_manager.db.execute_query(
                            "SELECT topic_kr, peer_user_name, peer_user_email FROM teams_chats WHERE user_id = ? AND chat_id = ?",
                            (user_id, chat_id),
                            fetch_result=True
                        )
                        if db_result and len(db_result) > 0:
                            topic_kr_val, peer_name_val, peer_email_val = db_result[0]
                            if topic_kr_val:
                                chat["topic_kr"] = topic_kr_val
                            if peer_name_val:
                                chat["peer_user_name"] = peer_name_val
                            if peer_email_val:
                                chat["peer_user_email"] = peer_email_val

            # 사용자 이름으로 필터링 (선택)
            if user_name_filter:
                filter_lower = user_name_filter.lower()
                filtered_chats = []
                for chat in chats:
                    topic = (chat.get("topic") or "").lower()
                    topic_kr = (chat.get("topic_kr") or "").lower()
                    peer_name = (chat.get("peer_user_name") or "").lower()

                    if filter_lower in topic or filter_lower in topic_kr or filter_lower in peer_name:
                        filtered_chats.append(chat)

                chats = filtered_chats
                result["filtered_by_user"] = user_name_filter

            # 사용자별로 그룹핑
            users_map = {}
            for chat in chats:
                chat_type = chat.get("chatType", "unknown")
                topic = chat.get("topic") or chat.get("peer_user_name") or "(제목 없음)"
                topic_kr = chat.get("topic_kr")

                # 표시 이름: 한글 이름 우선, 없으면 원본
                display_name = topic_kr if topic_kr else topic

                # 1:1 채팅은 사용자별로 정리
                if chat_type == "oneOnOne":
                    if display_name not in users_map:
                        users_map[display_name] = {
                            "user_name": display_name,
                            "chat_id": chat.get("id"),
                            "chat_type": chat_type,
                            "last_activity": chat.get("lastUpdatedDateTime"),
                            "message_count": 1
                        }
                    else:
                        users_map[display_name]["message_count"] += 1
                else:
                    # 그룹 채팅은 그대로 추가
                    group_key = f"[그룹] {display_name}"
                    if group_key not in users_map:
                        users_map[group_key] = {
                            "user_name": display_name,
                            "chat_id": chat.get("id"),
                            "chat_type": chat_type,
                            "last_activity": chat.get("lastUpdatedDateTime"),
                            "message_count": 1
                        }
                    else:
                        users_map[group_key]["message_count"] += 1

            # 리스트로 변환 및 정렬 (최근 활동순)
            users_list = list(users_map.values())
            users_list.sort(key=lambda x: x.get("last_activity", ""), reverse=True)

            result["chats"] = chats
            result["users"] = users_list
            result["user_count"] = len(users_list)

            return result

        except Exception as e:
            logger.error(f"❌ 날짜별 채팅 조회 오류: {str(e)}", exc_info=True)
            return {"success": False, "message": f"오류 발생: {str(e)}"}
