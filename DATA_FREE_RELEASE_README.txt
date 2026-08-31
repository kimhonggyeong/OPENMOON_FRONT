OPENMOON AI LAN 데이터 제외 배포본

이 배포본에는 메일, 첨부파일, 운영 DB, 견적서 및 단가 자료가 포함되어 있지 않습니다.

1. .env.example을 .env로 복사하고 메일 및 AI 설정을 입력합니다.
2. 준비한 데이터는 EXE 옆의 backend\data 아래에 직접 넣습니다.
3. OPENMOON_AI_LAN.exe를 실행합니다.
4. 서버장 PC는 '이 PC를 공유 서버로 실행'을 선택합니다.
5. 게스트 PC는 검색된 서버를 선택하거나 서버 IP를 입력합니다.

주요 데이터 위치
- backend\data\openmoon.db
- backend\data\source\price_table.db
- backend\data\source\quotation_history.db
- backend\data\source\price_table.xlsx
- backend\data\templates\quotation_template.xlsx
- backend\data\templates\quotation_customer_template.pdf
- backend\data\quotation_files\
- backend\data\raw_mails\
- backend\data\attachments\
- backend\data\generated_quotes\

주의
- 기존 운영 폴더에 업데이트할 때 backend\data와 .env는 덮어쓰거나 삭제하지 마세요.
- 실제 메일 발송 전까지 ALLOW_LIVE_SEND=false를 유지하세요.
