import json
import logging

from fastapi import HTTPException

from app import catalog as cat
from app.llm import call_llm
from app.models import ChatRequest, ChatResponse
from app.prompts import build_system_prompt

log = logging.getLogger(__name__)

MAX_TURNS = 8
TURN_LIMIT_REPLY = (
    "This conversation has reached the 8-turn limit. "
    "Please start a new session to continue."
)


def count_user_turns(messages: list) -> int:
    return sum(1 for m in messages if m.role == "user")


def build_query_for_retrieval(messages: list) -> str:
    user_msgs = [m.content for m in messages if m.role == "user"]
    recent = user_msgs[-3:] if len(user_msgs) >= 3 else user_msgs
    return " ".join(recent)


def get_catalog_context(query: str, top_k: int = 20) -> str:
    relevant = cat.hybrid_search(query, top_k=top_k)
    all_items = cat.get_all()

    seen_urls = {item["url"] for item in relevant}
    other_items = [i for i in all_items if i["url"] not in seen_urls]
    ordered = relevant + other_items

    compact = []
    for item in ordered:
        compact.append({
            "name": item["name"],
            "url": item["url"],
            "test_type": item.get("test_type", ""),
            "keys": item.get("keys", []),
            "duration": item.get("duration"),
            "description": (item.get("description", "") or "")[:150],
        })
    return json.dumps(compact, ensure_ascii=False)


def process_chat(request: ChatRequest) -> ChatResponse:
    messages = request.messages
    user_turns = count_user_turns(messages)

    if user_turns > MAX_TURNS:
        log.info(f"Turn limit exceeded: {user_turns} user turns.")
        return ChatResponse(
            reply=TURN_LIMIT_REPLY,
            recommendations=None,
            end_of_conversation=True,
        )

    query = build_query_for_retrieval(messages)
    catalog_json = get_catalog_context(query)
    system_content = build_system_prompt(catalog_json)

    llm_messages = [{"role": "system", "content": system_content}]
    for msg in messages:
        llm_messages.append({"role": msg.role, "content": msg.content})

    try:
        return call_llm(llm_messages)
    except Exception as exc:
        log.error(f"LLM call failed: {exc}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"LLM error: {exc}")
