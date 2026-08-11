"""LLM access with a deterministic rule-based fallback.

If the vLLM endpoint is unreachable (CI, tests, or before the model is up),
`llm_json` falls back to `mock_fn`, a deterministic function of the evidence.
This keeps the full agent graph executable without a GPU.
"""
import json
import re

from langchain_openai import ChatOpenAI

from backend.config import settings


def _client():
    return ChatOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        temperature=0.1,
        timeout=120,
        max_retries=1,
    )


def llm_json(system: str, user: str, mock_fn=None) -> dict:
    """Call the LLM expecting a JSON object; fall back to mock_fn on failure."""
    try:
        resp = _client().invoke([
            {"role": "system", "content": system + "\nRespond ONLY with a valid JSON object."},
            {"role": "user", "content": user},
        ])
        text = resp.content
        # strip <think> blocks (Qwen3) and code fences
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
        m = re.search(r"\{.*\}", text, flags=re.S)
        if not m:
            raise ValueError(f"no JSON in LLM output: {text[:200]}")
        return json.loads(m.group(0))
    except Exception as e:
        if mock_fn is None:
            raise
        out = mock_fn()
        out["_mock"] = True
        out["_mock_reason"] = str(e)[:200]
        return out


def llm_text(system: str, user: str, mock_fn=None) -> str:
    try:
        resp = _client().invoke([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
        return re.sub(r"<think>.*?</think>", "", resp.content, flags=re.S).strip()
    except Exception:
        if mock_fn is None:
            raise
        return mock_fn()
