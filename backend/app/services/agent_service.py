from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]

from ..config import Settings
from ..models import ChatMessage, Mail
from .agent_tools import OPENMOON_AGENT_TOOLS, AgentToolContext, execute_agent_tool
from .conversation_summary_service import get_or_refresh_summary
from .memory_service import memory_context_for_mail


MAX_AGENT_STEPS = 7
MAX_TOOL_OUTPUT_CHARS = 16_000
RECENT_CHAT_LIMIT = 8


@dataclass
class AgentResult:
    answer: str
    evidence: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    draft_updated: bool


def _instructions(
    mail: Mail,
    memory_context: list[dict[str, object]],
    conversation_summary: str | None,
) -> str:
    memory_text = json.dumps(memory_context, ensure_ascii=False, default=str)
    summary_text = conversation_summary or "없음"
    return f"""
당신은 디자인·인쇄 회사 '(주)열린문디자인'의 대화형 견적 업무 AI Agent입니다.

현재 작업:
- mail_id: {mail.id}
- 고객/기관: {mail.customer_organization or mail.customer_name or '미확인'}
- 메일 제목: {mail.original_subject or ''}
- 이전 긴 대화 요약: {summary_text}
- 현재 관련 장기기억: {memory_text}

목표:
사용자와 자연스럽게 대화하면서 현재 견적, 직원이 관리한 회사 지식, 고객별 장기기억,
과거 견적, 현재 단가표를 필요한 순서대로 조회하고 실제 견적 업무를 보조합니다.

근거 우선순위:
1. 사용자가 현재 대화에서 명확히 말한 내용
2. 현재 메일/현재 견적 상태
3. 직원이 직접 관리한 열린문디자인 회사 지식(search_company_knowledge)
4. 해당 고객의 장기기억(search_memory)
5. 해당 고객의 과거 실제 견적(search_quotation_history)
6. 현재 단가표/가격 엔진(search_current_price_candidates, search_price_table)
7. 일반적인 모델 지식

작업 규칙:
1. 열린문디자인의 실제 가격, 고객 이력, 회사 규칙을 추측하지 마세요. 반드시 Tool로 확인하세요.
2. '저번처럼', '전에 했던 것', '작년 것처럼', '원래 하던 대로'가 나오면 현재 고객을 확인한 뒤
   search_memory와 search_quotation_history를 사용하세요. 이전 단가를 적용하려면 현재 가격도 다시 확인하세요.
3. 재질/용도/내구성/표준 규격 추천은 먼저 search_company_knowledge를 사용하세요.
   필요하면 고객 memory와 history를 추가로 확인하세요. 내부 근거가 하나도 없을 때만 일반 지식을 쓰고
   반드시 '일반적인 재질 특성 기준'이라고 구분하세요.
4. 질문이나 추천 요청만으로 견적 값을 바꾸지 마세요. '적용해줘/바꿔줘/수정해줘'처럼 사용자가
   명확히 실행을 요청한 경우에만 update_quote_item을 사용하세요.
5. 규격/재질처럼 가격에 영향을 주는 값을 바꾼 뒤에는 이전 단가를 그대로 유지한다고 가정하지 마세요.
   시스템이 가격을 재평가하도록 하고, 필요하면 현재 가격 후보를 확인하세요.
6. 단가 직접 변경은 기존 서버의 명시적 단가 명령 로직이 담당합니다. Agent Tool로 임의 단가를 확정하지 않습니다.
7. remember_fact는 사용자가 명시한 장기 가치가 있는 고객 선호/회사 규칙/확정 사실에만 사용하세요.
   이번 주문의 수량 같은 일회성 값이나 AI 추론은 장기기억으로 저장하지 마세요.
8. 가격표/단가표/Excel 요청은 다음처럼 처리하세요.
   - '가격표', '단가표', '가격 출처', '단가 출처'를 묻는 경우 search_price_table을 사용하세요.
   - 사용자가 '엑셀', 'Excel', '가격표 파일', '단가표 파일'을 언급하면서 '열어줘', '보여줘', '띄워줘', '켜줘', '열기'처럼 실제 파일 열기를 요청하면 반드시 open_price_source를 호출하세요.
   - 품목명이 함께 있으면 먼저 search_price_table로 실제 시트/셀을 찾은 뒤 open_price_source를 호출하세요.
   - Microsoft Excel이 설치되지 않은 PC에서도 open_price_source는 기본 XLSX 뷰어로 여는 fallback을 지원합니다. 따라서 '엑셀 파일을 직접 열 수 없다'고 답하지 마세요. Tool 실행이 실패한 경우에만 실제 오류 내용을 안내하세요.
9. 사용자가 '견적서 만들어줘/생성해줘'라고 명확히 요청한 경우에만 create_quotation_draft를 호출하세요.
10. 견적서 생성 전 품목·규격·수량·단가·공급금액·합계를 확인합니다. 공급금액은 반드시 수량×단가입니다.
11. 이메일 최종 승인/발송은 실행하지 마세요. 해당 단계는 V4 및 담당자 승인 영역입니다.
12. 정보가 부족하면 추측해서 채우지 말고, 견적 진행에 가장 중요한 누락 정보 한 가지를 구체적으로 질문하세요.
13. Tool을 호출했으면 결과를 실제로 읽고 다음 행동을 판단하세요. 여러 Tool이 필요하면 한 번에 끝내지 말고
    결과를 보고 다음 Tool을 선택하세요.
14. 답변은 한국어로, 업무 화면에서 빠르게 읽을 수 있게 짧고 명확하게 작성하세요.
""".strip()


def _recent_chat_input(
    session: Session,
    mail_id: int,
    limit: int = RECENT_CHAT_LIMIT,
) -> list[dict[str, str]]:
    rows = session.scalars(
        select(ChatMessage)
        .where(ChatMessage.mail_id == mail_id)
        .order_by(ChatMessage.id.desc())
        .limit(limit)
    ).all()
    return [
        {"role": row.role, "content": row.content}
        for row in reversed(rows)
        if row.role in {"user", "assistant"}
    ]


def _compact_tool_output(result: dict[str, Any]) -> str:
    raw = json.dumps(result, ensure_ascii=False, default=str)
    return raw if len(raw) <= MAX_TOOL_OUTPUT_CHARS else raw[:MAX_TOOL_OUTPUT_CHARS] + "...(일부 생략)"


def run_agent(
    session: Session,
    settings: Settings,
    mail: Mail,
    text: str,
    *,
    user_message_id: int | None = None,
) -> AgentResult:
    if not settings.openai_api_key or OpenAI is None:
        raise RuntimeError("OPENAI_API_KEY가 없어 Agent 모드를 사용할 수 없습니다.")

    customer_name = mail.customer_organization or mail.customer_name
    product_names = [item.product_name for item in mail.items if item.product_name]
    memory_context = memory_context_for_mail(
        session,
        customer_name=customer_name,
        product_names=product_names,
        query=text,
        limit=6,
    )

    # 16개 이상의 긴 대화부터 오래된 메시지를 누적 요약하고 최근 8개만 원문으로 유지한다.
    conversation_summary = get_or_refresh_summary(
        session,
        settings,
        mail.id,
        recent_keep=RECENT_CHAT_LIMIT,
    )

    client = OpenAI(api_key=settings.openai_api_key)
    input_items: list[Any] = _recent_chat_input(
        session,
        mail.id,
        limit=RECENT_CHAT_LIMIT,
    )
    if not input_items or input_items[-1].get("role") != "user":
        input_items.append({"role": "user", "content": text})

    tool_context = AgentToolContext(
        session=session,
        settings=settings,
        mail=mail,
        user_message_id=user_message_id,
    )
    evidence: list[dict[str, Any]] = []

    for _ in range(MAX_AGENT_STEPS):
        response = client.responses.create(
            model=settings.openai_model,
            instructions=_instructions(
                mail,
                memory_context,
                conversation_summary,
            ),
            input=input_items,
            tools=OPENMOON_AGENT_TOOLS,
        )

        # Responses API의 function-calling 루프: 모델 output을 유지하고
        # 각 function_call_output을 추가한 뒤 다음 판단을 요청한다.
        input_items.extend(response.output)
        tool_calls = [
            item
            for item in response.output
            if getattr(item, "type", None) == "function_call"
        ]

        if not tool_calls:
            session.flush()
            return AgentResult(
                answer=response.output_text or "답변을 생성하지 못했습니다.",
                evidence=evidence,
                actions=list(tool_context.actions),
                draft_updated=tool_context.draft_updated,
            )

        for call in tool_calls:
            try:
                arguments = json.loads(call.arguments or "{}")
                result, tool_evidence = execute_agent_tool(
                    tool_context,
                    call.name,
                    arguments,
                )
                evidence.extend(tool_evidence)
                tool_output = _compact_tool_output(result)
            except Exception as error:
                tool_output = json.dumps(
                    {
                        "ok": False,
                        "error": str(error),
                        "tool": getattr(call, "name", ""),
                    },
                    ensure_ascii=False,
                )

            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": tool_output,
                }
            )

    return AgentResult(
        answer=(
            "조회 단계가 너무 많아 요청을 끝까지 처리하지 못했습니다. "
            "대상 고객·품목·원하는 작업을 조금 더 구체적으로 말씀해 주세요."
        ),
        evidence=evidence,
        actions=list(tool_context.actions),
        draft_updated=tool_context.draft_updated,
    )
