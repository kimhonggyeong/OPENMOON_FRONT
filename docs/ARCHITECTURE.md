# 시스템 아키텍처

## 처리 흐름

```text
Daum IMAP / EML 업로드
        ↓
메일 원문 보존
        ↓
전달 메일 안쪽 실제 고객 헤더 추출
        ↓
첨부파일 로컬 저장 및 텍스트·이미지 분석
        ↓
LLM 구조화 분석 또는 규칙 기반 폴백
        ↓
고객 식별 및 과거 견적 연결
        ↓
현재 단가표 후보 검색
        ↓
검토 필요 판정
   ├─ 차단 항목 존재 → REVIEW_REQUIRED
   └─ 차단 항목 없음 → READY_FOR_QUOTE
        ↓
Excel 견적서 초안 생성
        ↓
담당자 승인
        ↓
SMTP 발송
```

## 계층

### API

- `routers/mails.py`: 메일 동기화, EML 업로드, 분석, 수정
- `routers/reviews.py`: 검토 항목 해결
- `routers/quotations.py`: 견적 생성, 승인, 발송
- `routers/imports.py`: 단가표 및 기존 견적 Import

### 업무 서비스

- `mail_service.py`: IMAP/MIME/EML
- `forwarded_mail_parser.py`: Daum 전달 본문 원본 추출
- `attachment_service.py`: HWPX, PDF, Excel, 이미지 분기
- `llm_service.py`: 구조화 출력과 규칙 기반 분석
- `customer_matcher.py`: 기관명·이메일 고객 연결
- `history_service.py`: 과거 견적 일괄 Import와 검색
- `price_service.py`: AI 단가 시트 및 현수막 표 검색
- `review_service.py`: 누락·충돌 차단
- `quotation_service.py`: 템플릿 복제 및 Excel 생성
- `smtp_service.py`: 승인된 견적 발송

## 데이터 저장 원칙

- 원본 견적서는 기존 폴더에 유지
- DB에는 구조화 데이터와 원본 파일 경로만 저장
- 원본 메일과 첨부파일은 로컬 폴더에 보존
- 내부 원가와 마진은 고객용 견적에 출력하지 않음
- 모든 가격 후보는 원본 시트와 셀 주소를 보존
