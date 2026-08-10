# OPENMOON AI 견적 업무 보조 시스템

열린문디자인의 주문 메일을 분석하고, 첨부파일·기존 견적 이력·현재 단가표를 함께 조회하여 견적서 초안을 만드는 로컬 업무 보조 시스템입니다.

> 기본 원칙: 정보가 누락되거나 가격 근거가 불명확한 메일은 자동 처리하지 않고 **검토 필요**로 분리합니다. 담당자 승인 전에는 메일을 발송하지 않습니다.

## 주요 기능

- Daum IMAP 메일 동기화 및 `.eml` 수동 업로드
- 전달 메일 안쪽의 실제 고객 메일 추출
- HWPX, PDF, Excel, 이미지 첨부파일 분석
- OpenAI 구조화 출력 기반 주문정보 추출
- OpenAI API가 없어도 동작하는 기본 규칙 분석
- 전체 과거 견적서 폴더 일괄 DB 변환
- 동일 고객·동일 품목의 최근 견적 검색
- 현재 단가표와 과거 견적 비교
- 누락·충돌·첨부파일 실패를 검토 필요로 분류
- Excel 견적서 초안 생성
- 담당자 승인 후 SMTP 발송
- React 기반 3단 업무 화면

## 권장 실행 환경

- Windows 11
- Python 3.11 또는 3.12
- Node.js 20 이상
- 최초 MVP: 회사 PC 1대, SQLite

## 1. 설치

프로젝트 폴더에서 `setup.bat`을 실행합니다.

```powershell
setup.bat
```

직접 설치하려면:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
cd frontend
npm install
npm run build
cd ..
```

## 2. 환경변수

`.env.example`을 `.env`로 복사하고 값을 입력합니다.

```powershell
copy .env.example .env
```

필수값:

```env
DAUM_LOGIN_ID=
DAUM_APP_PASSWORD=
OPENAI_API_KEY=
```

OpenAI 키가 없으면 규칙 기반 분석만 수행하며, 이미지 첨부는 자동 분석하지 않고 검토 필요로 보냅니다.

실제 발송은 기본적으로 비활성화되어 있습니다.

```env
ALLOW_LIVE_SEND=false
```

테스트가 끝난 뒤에만 `true`로 변경하세요.

## 3. 실행

개발 모드:

```powershell
start-dev.bat
```

빌드된 프론트엔드를 포함한 단일 실행:

```powershell
start.bat
```

브라우저에서 다음 주소를 엽니다.

- UI: http://127.0.0.1:8000
- API 문서: http://127.0.0.1:8000/docs

## 4. 초기 데이터 가져오기

### 단가표

기본 단가표는 다음 위치에 포함되어 있습니다.

```text
backend/data/source/price_table.xlsx
```

UI의 설정 메뉴 또는 API에서 가져올 수 있습니다.

```powershell
python -m backend.scripts.import_price_table
```

### 기존 견적 전체 이력

회사 PC의 견적 폴더를 직접 읽습니다.

```powershell
python -m backend.scripts.import_quotation_history `
  --input "D:\열린문디자인\견적서"
```

원본 Excel은 이동하거나 복사하지 않습니다. DB에는 고객명, 견적일, 품목, 규격, 수량, 단가, 금액, 원본 경로만 저장합니다.

결과 로그:

```text
backend/data/import_summary.csv
backend/data/import_errors.csv
```

## 5. 검토 필요 처리 원칙

다음 조건은 자동 견적 생성이 차단됩니다.

- 고객 식별 실패
- 품목 누락
- 수량 누락
- 품목별 필수 규격 누락
- `지난번처럼`, `작년 것처럼`의 대상 불명확
- 첨부파일 분석 실패 또는 지원하지 않는 HWP
- 정확한 단가 후보 없음
- 단가표와 과거 견적이 충돌
- LLM 분석 신뢰도 부족
- VAT, 시공비, 배송비 등 가격 결정 조건 누락

검토 화면에서 값을 입력하고 `검토 완료`를 누르면 다시 견적 생성 가능 여부를 계산합니다.

## 6. 데이터 저장 위치

```text
backend/data/openmoon.db             SQLite DB
backend/data/raw_mails/              원본 EML
backend/data/attachments/            메일 첨부파일
backend/data/generated_quotes/       생성된 견적서
backend/data/templates/              견적서 템플릿
backend/data/source/                 단가표 원본
```

## 7. 운영 전 확인사항

- 회사 데이터의 OpenAI API 전송 허용 여부
- 실제 견적서 템플릿 셀 위치
- SMTP 테스트 수신자
- VAT, 배송, 시공, 철거 규칙
- 회사 내부 원가·마진 노출 차단
- 전체 견적 이력 Import 성공률

## 8. EXE 패키징

먼저 프론트엔드를 빌드합니다.

```powershell
cd frontend
npm run build
cd ..
```

그다음:

```powershell
build-exe.bat
```

`dist/OPENMOON_AI/OPENMOON_AI.exe`가 생성됩니다. PyInstaller 패키징은 회사 PC 환경에서 최종 검증이 필요합니다.

## 현재 버전의 범위

이 ZIP은 실제 실행 가능한 MVP 골격과 핵심 로직을 포함합니다. 다만 다음 항목은 회사 데이터 전체로 검증하며 조정해야 합니다.

- 2025·2026 견적서의 예외 양식
- HWP 자동 변환
- 이미지 속 재질·크기 판정
- 품목별 세부 가격 규칙
- 다중 사용자·중앙 서버 운영
