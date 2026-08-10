# Build verification

검증일: 2026-08-04

## 자동 검사

- Python `compileall`: 통과
- JavaScript `node --check`: 통과
- Pytest: 5개 통과
- FastAPI TestClient 핵심 API: 통과

## 단가표 검증

기본 단가표 Import 결과:

- 품목 별칭: 84건
- 가격 규칙: 5,081건
- 텍스트 업무 규칙: 145건
- 원본 검토 플래그: 51건
- 현수막 4000×600mm: 44,000원, 원본 `현수막!J5` 정확 검색 확인

## 견적 이력 샘플 검증

업로드된 2025년 견적 샘플 9개 파일로 확인:

- 견적 시트 Import: 71건
- 품목 Import: 168건
- 실패 파일: 0건

전체 2025·2026 폴더에서는 예외 양식이 추가로 발견될 수 있으므로 `import_errors.csv`를 확인해야 합니다.

## 제한사항

- npm 패키지 저장소가 현재 실행 환경에서 접근되지 않아 React 소스의 npm 빌드는 수행하지 못했습니다.
- 대신 외부 패키지 없이 실행 가능한 사전 빌드 UI를 `frontend/dist`에 포함했습니다.
- 회사 PC에서는 `npm install && npm run build`로 React UI를 다시 빌드할 수 있습니다.
