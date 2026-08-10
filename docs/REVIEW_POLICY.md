# 검토 필요 정책

## 차단 항목

다음 이슈가 하나라도 미해결이면 견적 생성 버튼을 비활성화합니다.

- `CUSTOMER_NOT_IDENTIFIED`: 고객 기관 식별 실패
- `NO_ORDER_ITEM`: 품목 없음
- `MISSING_*`: 품목별 필수정보 누락
- `NO_PRICE_CANDIDATE`: 단가 후보 없음
- `PRICE_NOT_EXACT`: 현재 조건과 정확히 일치하는 단가 없음
- `ATTACHMENT_REVIEW_REQUIRED`: 첨부 분석 실패·미지원·스캔 미처리
- `UNRESOLVED_HISTORY_REFERENCE`: 지난번/작년 자료 연결 실패

## 경고 항목

경고는 화면에 표시하지만 견적 생성을 차단하지 않습니다.

- 낮은 LLM 분석 신뢰도
- LLM이 추가 확인을 권고한 정보

## 해결 방식

1. 과거 동일 고객 견적 후보 적용
2. 현재 단가표 후보를 담당자가 선택
3. 직접 값 입력
4. 고객 확인 후 직접 입력

직접 입력된 값은 `confirmed=true`로 저장됩니다. 직접 확정한 단가는 단가표 정확일치 검사를 다시 차단하지 않습니다.
