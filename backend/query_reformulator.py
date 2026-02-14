from __future__ import annotations

import os
import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
REFORMULATOR_MODEL = os.getenv("OPENROUTER_REFORMULATOR_MODEL", "deepseek/deepseek-chat")


def reformulate_query(question: str, use_llm: bool = True) -> str:
    """
    Rewrite a vague question into a retrieval-friendly query.
    Falls back to the original question when LLM mode or API access is unavailable.
    """
    q = (question or "").strip()
    if not q:
        return q
    if not use_llm or len(q.split()) > 15:
        return q

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return q

    try:
        response = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": REFORMULATOR_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a query reformulator for a company policy knowledge base. "
                            "Rewrite the user's question to be specific and retrieval-friendly. "
                            "Expand abbreviations, add relevant policy terms, and make the intent explicit. "
                            "Return ONLY the rewritten question, nothing else. "
                            "If the question is already specific, return it unchanged."
                        ),
                    },
                    {"role": "user", "content": q},
                ],
                "max_tokens": 100,
                "temperature": 0,
            },
            timeout=3,
        )
        if not response.ok:
            return q
        result = response.json()
        reformulated = result["choices"][0]["message"]["content"].strip()
        return reformulated if reformulated else q
    except Exception:
        return q
