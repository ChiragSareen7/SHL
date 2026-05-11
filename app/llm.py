import json
import logging
import os
import re
from typing import Optional

from openai import OpenAI

from app import catalog as cat
from app.models import ChatResponse, Recommendation

log = logging.getLogger(__name__)

_client: Optional[OpenAI] = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY environment variable not set.")
        _client = OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
    return _client


def _model() -> str:
    return os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")


def _extract_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?\s*", "", text).replace("```", "")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in LLM output: {text[:300]}")
    return json.loads(text[start: end + 1])


def _validate_and_build_response(raw: dict) -> ChatResponse:
    reply = raw.get("reply", "")
    if not isinstance(reply, str):
        reply = str(reply)

    eoc = raw.get("end_of_conversation", False)
    if not isinstance(eoc, bool):
        eoc = str(eoc).lower() == "true"

    recs_raw = raw.get("recommendations")
    recommendations: Optional[list[Recommendation]] = None

    if recs_raw and isinstance(recs_raw, list):
        validated, invalid_urls = [], []
        for rec in recs_raw:
            if not isinstance(rec, dict):
                continue
            url = rec.get("url", "")
            if cat.url_exists(url):
                validated.append(Recommendation(
                    name=rec.get("name", ""),
                    url=url,
                    test_type=rec.get("test_type", ""),
                ))
            else:
                log.warning(f"LLM returned unknown URL: {url!r}")
                invalid_urls.append(url)

        if invalid_urls:
            raise ValueError(f"LLM returned {len(invalid_urls)} unknown URL(s): {invalid_urls}")

        recommendations = validated if validated else None

    return ChatResponse(reply=reply, recommendations=recommendations, end_of_conversation=eoc)


def call_llm(
    messages: list[dict],
    temperature: float = 0.1,
    max_tokens: int = 1024,
) -> ChatResponse:
    client = get_client()
    model = _model()

    for attempt in range(2):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content or ""
        log.debug(f"LLM raw output (attempt {attempt + 1}): {content[:500]}")

        try:
            return _validate_and_build_response(_extract_json(content))
        except ValueError as exc:
            if attempt == 0 and "unknown URL" in str(exc):
                log.warning(f"URL validation failed, retrying: {exc}")
                messages = messages + [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": (
                        "Your previous response contained URLs that do not exist in the catalog. "
                        "You MUST only use URLs that exactly match those in the catalog. "
                        "Please respond again with only valid catalog URLs."
                    )},
                ]
                continue
            raise
        except json.JSONDecodeError as exc:
            if attempt == 0:
                log.warning(f"JSON parse failed, retrying: {exc}")
                messages = messages + [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": (
                        "Your previous response was not valid JSON. "
                        "Respond ONLY with a valid JSON object. No text before or after the JSON."
                    )},
                ]
                continue
            raise RuntimeError(f"LLM response unparseable after 2 attempts: {exc}") from exc

    raise RuntimeError("LLM call failed after 2 attempts.")
