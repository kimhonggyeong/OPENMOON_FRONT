# Runtime data

- `source/price_table.xlsx`: 현재 단가표 원본
- `templates/quotation_template.xlsx`: 견적서 생성 템플릿
- `openmoon.db`: 최초 실행 시 생성되는 SQLite DB
- `raw_mails/`: 원본 EML
- `attachments/`: 메일 첨부파일
- `generated_quotes/`: 생성된 견적서

원본 견적 이력 파일은 이 폴더로 복사하지 않습니다. Import 시 회사 PC의 기존 폴더 경로만 DB에 기록합니다.
