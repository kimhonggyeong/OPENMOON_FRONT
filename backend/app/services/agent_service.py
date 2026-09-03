from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import ChatMessage, GeneralChatMessage, Mail
from .agent_tools import (
    GENERAL_AGENT_TOOLS,
    OPENMOON_AGENT_TOOLS,
    AgentToolContext,
    execute_agent_tool,
)
from .conversation_summary_service import get_or_refresh_summary
from .memory_service import memory_context_for_mail
from .ai_provider import (
    create_anthropic_client,
    create_openai_client,
    is_ai_configured,
    text_from_anthropic_message,
)


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
    product_summary = ", ".join(
        dict.fromkeys(item.product_name for item in mail.items if item.product_name)
    ) or "아직 확인된 품목 없음"
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

답변 범위:
- 이 Agent는 견적/제작/납품 업무를 돕는 전문가입니다. 날씨·안부·잡담처럼 이번 견적
  업무와 무관한 질문에는 짧고 무난하게만 답하고, 곧바로 현재 진행 중인 견적으로
  대화를 되돌리세요. 잡담에 깊이 관여하거나 개인적인 의견을 길게 늘어놓지 마세요.
- 반대로 지금 담긴 품목의 제작·규격·시공·납품과 관련된 질문에는 회사 담당자 수준으로
  구체적이고 적극적으로 답하세요. 사용자가 "더 고려할 게 없을까?" 처럼 열린 질문을
  하면, 하나로만 답하지 말고 지금 메일에 담긴 품목({product_summary}) 기준으로
  실무에서 자주 놓치는 점(예: 현수막이면 아일렛 위치·방수/내구성·시공 방식·계절/바람
  하중·설치 장소별 유의점, 명함/배너류면 재단선·도련·코팅·인쇄면 등)을 먼저
  search_company_knowledge(product_name, usage_context 지정)로 확인해서 답하세요.
  내부 회사 지식에 없으면 일반적인 업계 지식임을 밝히고 조언하세요(근거 우선순위 3
  참고). 사용자가 묻지 않은 것까지 먼저 짚어주는 것이 이 Agent의 핵심 가치입니다.

근거 우선순위:
1. 사용자가 현재 대화에서 명확히 말한 내용
2. 현재 메일/현재 견적 상태 및 첨부파일 내용(read_mail_attachments)
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
5-1. update_quote_item/add_quote_item/replace_quote_items/delete_quote_item으로 품목을 바꾸면,
   이미 Excel 견적서 파일이 만들어져 있는 경우 그 파일도 자동으로 같은 내용으로 다시 저장됩니다
   (별도 Tool 호출 불필요). Tool 결과의 draft_file_updated가 true이면 "이미 만든 견적서 파일에도
   반영했습니다"라고 답하고, false인데 이미 만든 견적서가 있는 상황이면 검토 대기 항목이나
   빈 필수값 때문에 파일까지는 반영되지 않았다는 점을 안내하세요.
6. 단가 직접 변경은 기존 서버의 명시적 단가 명령 로직이 담당합니다. Agent Tool로 임의 단가를 확정하지 않습니다.
7. remember_fact는 사용자가 명시한 장기 가치가 있는 고객 선호/회사 규칙/확정 사실에만 사용하세요.
   이번 주문의 수량 같은 일회성 값이나 AI 추론은 장기기억으로 저장하지 마세요.
8. 가격표/단가표/Excel 요청은 다음처럼 처리하세요.
   - '가격표', '단가표', '가격 출처', '단가 출처'를 묻는 경우 search_price_table을 사용하세요.
   - 사용자가 '엑셀', 'Excel', '가격표 파일', '단가표 파일'을 언급하면서 '열어줘', '보여줘', '띄워줘', '켜줘', '열기'처럼 실제 파일 열기를 요청하면 반드시 open_price_source를 호출하세요.
   - 품목명이 함께 있으면 먼저 search_price_table로 실제 시트/셀을 찾은 뒤 open_price_source를 호출하세요.
   - Microsoft Excel이 설치되지 않은 PC에서도 open_price_source는 기본 XLSX 뷰어로 여는 fallback을 지원합니다. 따라서 '엑셀 파일을 직접 열 수 없다'고 답하지 마세요. Tool 실행이 실패한 경우에만 실제 오류 내용을 안내하세요.
9. 과거 견적 Excel 요청은 다음처럼 처리하세요.
   - 먼저 search_quotation_history로 실제 과거 견적을 검색하세요.
   - 사용자가 '엑셀 열어줘/파일 보여줘/해당 견적 띄워줘'라고 명시한 경우에만 검색 결과의 source_file과 source_sheet를 그대로 사용해 open_quotation_source를 호출하세요.
   - 후보가 여러 개면 임의로 열지 말고 날짜·품목을 짧게 제시한 뒤 어느 견적인지 질문하세요.
10. 자연어 품목 명령은 다음처럼 처리하세요.
   - '추가해줘'는 add_quote_item, 특정 품목 변경은 update_quote_item, 삭제는 delete_quote_item을 사용하세요.
   - 사용자가 여러 품목을 새 견적으로 작성하며 '이 내용으로 해줘/품목을 이렇게 바꿔줘'라고 명확히 말한 경우 replace_quote_items를 사용하세요.
   - 사용자가 한 메시지에 품목 목록을 적고 '견적 내줘/견적서 만들어줘/부탁해'라고 요청하면 그 목록을 이번 견적의 전체 품목으로 보고 replace_quote_items를 먼저 호출한 뒤, 결과를 확인하고 create_quotation_draft를 호출하세요.
   - 사용자가 말하지 않은 규격·수량·단위·용지·인쇄면·재질·단가는 null로 두고 추측하지 마세요.
   - unit_price는 사용자가 현재 메시지에서 단가를 명시한 경우에만 전달하세요. 과거 가격이나 단가표 가격을 사용자 확인 없이 확정값으로 넣지 마세요.
11. 사용자가 '견적서 만들어줘/생성해줘'라고 명확히 요청한 경우에만 create_quotation_draft를 호출하세요. 이 도구는 파일을 임의 생성하지 않고 저장 방식 선택 창을 요청합니다.
12. 견적서 생성 전 품목·규격·수량·단가·공급금액·합계를 확인합니다. 공급금액은 반드시 수량×단가입니다.
13. 이메일 최종 승인/발송은 실행하지 마세요. 해당 단계는 담당자 승인 영역입니다.
14. 정보가 부족하면 추측해서 채우지 말고, 견적 진행에 가장 중요한 누락 정보 한 가지를 구체적으로 질문하세요.
15. Tool을 호출했으면 결과를 실제로 읽고 다음 행동을 판단하세요. 여러 Tool이 필요하면 한 번에 끝내지 말고
    결과를 보고 다음 Tool을 선택하세요.
16. 답변은 한국어로, 업무 화면에서 빠르게 읽을 수 있게 짧고 명확하게 작성하세요.
17. 사용자가 첨부파일·사진·시안·도면·스캔본의 내용을 묻거나, 규격/수량/디자인 판단에 첨부파일 내용이
    필요하면 read_mail_attachments로 실제 내용을 확인한 뒤 답하세요. 열어보지 않고 파일 내용을 추측하지
    마세요. HWP 미리보기 기반 추출이나 이미지 분석 결과는 불완전할 수 있으니, Tool 결과에 그런 안내가
    있으면 사용자에게도 그 한계를 알려주세요.
""".strip()


def _general_instructions(*, web_search_enabled: bool) -> str:
    web_search_line = (
        "4. 내부 자료에 없는 법률·트렌드·시사 질문은 web_search로 실제 최신 정보를 확인한 뒤 "
        "답하고, 어디서 확인했는지 밝히세요."
        if web_search_enabled
        else "4. 이 연결에는 실시간 웹 검색이 없습니다. 내부 자료에 없는 최신 법률·트렌드 질문은 "
        "일반적인 모델 지식 기준임을 밝히고, 확정 전 실제 확인이 필요하다고 안내하세요."
    )
    return f"""
당신은 디자인·인쇄 회사 '(주)열린문디자인'의 업무 상담 AI Agent입니다.

현재 상황:
- 이 대화는 특정 메일이나 특정 견적에 묶여 있지 않습니다. 지금 열린 견적을 조회하거나
  수정할 수 없고, 특정 고객의 과거 견적도 조회할 수 없습니다. 그런 요청이 오면 "특정 메일을
  열고 그 메일의 견적 에이전트에게 물어봐 주세요"라고 안내하세요.

목표:
- 특정 견적과 무관하게 제작 전반(배너·현수막·명함 등 각 품목의 제작·시공·규격 고려사항),
  법적으로 문제될 수 있는 요소(저작권/초상권, 옥외광고물 신고 등), 업계 트렌드처럼
  "지금 뭘 만들고 있는데 뭘 더 고려해야 할지" 같은 자유로운 질문에 답하는 창구입니다.
- 사용자가 묻지 않은 것까지 실무자 입장에서 먼저 짚어주는 것이 핵심 가치입니다. 하나로
  뭉뚱그리지 말고 구체적인 체크리스트로 답하세요.
- 이번 견적 업무와 무관한 잡담(날씨·안부 등)에는 짧고 무난하게만 답하세요.

근거 우선순위:
1. 직원이 직접 관리한 열린문디자인 회사 지식(search_company_knowledge)
2. 회사 전반 장기기억(search_memory)
3. 현재 단가표(search_price_table, open_price_source)
{web_search_line}
5. 일반적인 모델 지식(법률 자문이 아니라 참고용 안내임을 밝힐 것)

작업 규칙:
1. 열린문디자인의 실제 가격, 회사 규칙을 추측하지 마세요. 반드시 Tool로 확인하세요.
2. 법률 관련 질문에는 최종 판단은 실제 법률 자문/관할 기관 확인이 필요하다는 점을 짧게
   덧붙이세요. 다만 실무자가 바로 참고할 수 있는 구체적인 방향은 회피하지 말고 제시하세요.
3. 답변은 한국어로, 업무 화면에서 빠르게 읽을 수 있게 짧고 명확하게 작성하세요.
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


def _recent_general_chat_input(
    session: Session,
    limit: int = RECENT_CHAT_LIMIT,
) -> list[dict[str, str]]:
    rows = session.scalars(
        select(GeneralChatMessage)
        .order_by(GeneralChatMessage.id.desc())
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


def _anthropic_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "input_schema": tool.get("parameters", {"type": "object", "properties": {}}),
        }
        for tool in tools
        if tool.get("type") == "function"
    ]


def _run_openai_agent(
    settings: Settings,
    input_items: list[Any],
    instructions: str,
    tool_context: AgentToolContext,
    *,
    tools: list[dict[str, Any]],
    web_search_enabled: bool = False,
) -> AgentResult:
    client = create_openai_client(settings)
    evidence: list[dict[str, Any]] = []
    # OpenAI 호스팅 web_search 도구는 우리가 execute_agent_tool로 실행하지 않는다.
    # 모델이 호출하면 OpenAI 서버가 검색을 수행하고 결과를 그대로 답변에 반영한다.
    request_tools = [*tools, {"type": "web_search"}] if web_search_enabled else tools

    for _ in range(MAX_AGENT_STEPS):
        response = client.responses.create(
            model=settings.openai_model,
            instructions=instructions,
            input=input_items,
            tools=request_tools,
        )
        input_items.extend(response.output)
        tool_calls = [item for item in response.output if getattr(item, "type", None) == "function_call"]
        if not tool_calls:
            tool_context.session.flush()
            return AgentResult(
                answer=response.output_text or "답변을 생성하지 못했습니다.",
                evidence=evidence,
                actions=list(tool_context.actions),
                draft_updated=tool_context.draft_updated,
            )
        for call in tool_calls:
            try:
                arguments = json.loads(call.arguments or "{}")
                result, tool_evidence = execute_agent_tool(tool_context, call.name, arguments)
                evidence.extend(tool_evidence)
                tool_output = _compact_tool_output(result)
            except Exception as error:
                tool_output = json.dumps(
                    {"ok": False, "error": str(error), "tool": getattr(call, "name", "")},
                    ensure_ascii=False,
                )
            input_items.append({"type": "function_call_output", "call_id": call.call_id, "output": tool_output})

    return _agent_step_limit_result(tool_context, evidence)


def _run_anthropic_agent(
    settings: Settings,
    messages: list[Any],
    instructions: str,
    tool_context: AgentToolContext,
    *,
    tools: list[dict[str, Any]],
) -> AgentResult:
    client = create_anthropic_client(settings)
    evidence: list[dict[str, Any]] = []

    for _ in range(MAX_AGENT_STEPS):
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=settings.anthropic_max_tokens,
            system=instructions,
            messages=messages,
            tools=_anthropic_tools(tools),
        )
        tool_calls = [block for block in response.content if getattr(block, "type", None) == "tool_use"]
        if not tool_calls:
            tool_context.session.flush()
            return AgentResult(
                answer=text_from_anthropic_message(response) or "답변을 생성하지 못했습니다.",
                evidence=evidence,
                actions=list(tool_context.actions),
                draft_updated=tool_context.draft_updated,
            )

        messages.append({
            "role": "assistant",
            "content": [block.model_dump(exclude_none=True) for block in response.content],
        })
        tool_results: list[dict[str, Any]] = []
        for call in tool_calls:
            try:
                result, tool_evidence = execute_agent_tool(tool_context, call.name, dict(call.input or {}))
                evidence.extend(tool_evidence)
                tool_output = _compact_tool_output(result)
                is_error = False
            except Exception as error:
                tool_output = json.dumps(
                    {"ok": False, "error": str(error), "tool": getattr(call, "name", "")},
                    ensure_ascii=False,
                )
                is_error = True
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": tool_output,
                "is_error": is_error,
            })
        messages.append({"role": "user", "content": tool_results})

    return _agent_step_limit_result(tool_context, evidence)


def _agent_step_limit_result(
    tool_context: AgentToolContext,
    evidence: list[dict[str, Any]],
) -> AgentResult:
    return AgentResult(
        answer=(
            "조회 단계가 너무 많아 요청을 끝까지 처리하지 못했습니다. "
            "대상 고객·품목·원하는 작업을 조금 더 구체적으로 말씀해 주세요."
        ),
        evidence=evidence,
        actions=list(tool_context.actions),
        draft_updated=tool_context.draft_updated,
    )


def run_agent(
    session: Session,
    settings: Settings,
    mail: Mail,
    text: str,
    *,
    user_message_id: int | None = None,
) -> AgentResult:
    if not is_ai_configured(settings):
        raise RuntimeError("선택된 AI 공급자의 API 키 또는 패키지가 없어 Agent 모드를 사용할 수 없습니다.")

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
    instructions = _instructions(mail, memory_context, conversation_summary)
    if settings.llm_provider == "anthropic":
        return _run_anthropic_agent(
            settings, input_items, instructions, tool_context, tools=OPENMOON_AGENT_TOOLS
        )
    return _run_openai_agent(
        settings, input_items, instructions, tool_context, tools=OPENMOON_AGENT_TOOLS
    )


def run_general_agent(
    session: Session,
    settings: Settings,
    text: str,
    *,
    user_message_id: int | None = None,
) -> AgentResult:
    """특정 메일/견적과 무관한 일반 상담(제작 전반·법률·트렌드 질문 등)을 처리한다."""
    if not is_ai_configured(settings):
        raise RuntimeError("선택된 AI 공급자의 API 키 또는 패키지가 없어 Agent 모드를 사용할 수 없습니다.")

    input_items: list[Any] = _recent_general_chat_input(session, limit=RECENT_CHAT_LIMIT)
    if not input_items or input_items[-1].get("role") != "user":
        input_items.append({"role": "user", "content": text})

    tool_context = AgentToolContext(
        session=session,
        settings=settings,
        user_message_id=user_message_id,
    )

    # web_search는 지금 OpenAI Responses API 경로에서만 확인/연결했다.
    # Anthropic으로 전환해 쓰는 경우엔 별도 웹 검색 도구 연동이 필요하다.
    web_search_enabled = settings.llm_provider != "anthropic"
    instructions = _general_instructions(web_search_enabled=web_search_enabled)

    if settings.llm_provider == "anthropic":
        return _run_anthropic_agent(
            settings, input_items, instructions, tool_context, tools=GENERAL_AGENT_TOOLS
        )
    return _run_openai_agent(
        settings,
        input_items,
        instructions,
        tool_context,
        tools=GENERAL_AGENT_TOOLS,
        web_search_enabled=web_search_enabled,
    )
