# 템플릿 적용 가능성 분석

## ✅ 템플릿 적용 가능 모듈

### 1. **OneDrive MCP** ✅ (테스트 완료)
- **도구 수**: 5개
- **구조**: 단순, request/response 클래스 사용
- **특이사항**: create_folder는 dict 사용
- **결과**: 성공적으로 자동화

### 2. **Calendar MCP**
- **도구 수**: 5개
- **구조**: 표준 request/response 패턴
- **예상 난이도**: ⭐⭐ (쉬움)

### 3. **Mail IACS**
- **도구 수**: 4개
- **구조**: 표준 패턴
- **예상 난이도**: ⭐⭐ (쉬움)

### 4. **Teams MCP**
- **도구 수**: 6개
- **구조**: 복잡한 helper 메서드 포함
- **예상 난이도**: ⭐⭐⭐ (중간)

## ⚠️ 템플릿 수정 필요 모듈

### 1. **OneNote MCP** ❌
- **문제점**: action 기반 동적 라우팅
  - `manage_sections_and_pages`는 action에 따라 다른 메서드 호출
  - `manage_page_content`도 동일한 패턴
- **해결 방법**:
  - Option 1: 템플릿에 action 라우팅 지원 추가
  - Option 2: wrapper 메서드를 handlers.py에 수동 추가
  - Option 3: 도구를 세분화 (하나의 도구를 여러 개로 분리)

### 2. **Mail Query MCP** ❌
- **문제점**: 다중 상속, 복잡한 도구 aggregation
- **해결 방법**: 상속 지원 템플릿 필요

### 3. **Enrollment MCP** ❌
- **문제점**: 매우 복잡한 로직, 1000+ 줄
- **해결 방법**: 부분 자동화만 적용

## 📊 요약

| 모듈 | 도구 수 | 난이도 | 템플릿 적용 | 비고 |
|------|---------|--------|------------|------|
| **OneDrive** | 5 | ⭐⭐ | ✅ 완료 | 테스트 성공 |
| **Calendar** | 5 | ⭐⭐ | ✅ 가능 | |
| **Mail IACS** | 4 | ⭐⭐ | ✅ 가능 | |
| **Teams** | 6 | ⭐⭐⭐ | ✅ 가능 | |
| **OneNote** | 5 | ⭐⭐⭐⭐ | ⚠️ 수정필요 | action 라우팅 |
| **Mail Query** | 7+ | ⭐⭐⭐⭐⭐ | ⚠️ 수정필요 | 다중 상속 |
| **Enrollment** | ? | ⭐⭐⭐⭐⭐ | ❌ 복잡 | |

## 🚀 다음 단계

1. **즉시 적용 가능**: Calendar, Mail IACS
2. **약간 수정 후 적용**: Teams
3. **템플릿 개선 필요**: OneNote, Mail Query
4. **수동 유지**: Enrollment

## 💡 템플릿 개선 아이디어

### Action 라우팅 지원
```yaml
tools:
  - name: "manage_sections"
    type: "action_based"  # 새로운 타입
    actions:
      - name: "create_section"
        method: "create_section"
      - name: "list_sections"
        method: "list_sections"
```

### 다중 상속 지원
```yaml
service:
  base_classes:
    - AttachmentFilterHandlers
    - CalendarHandlers
```