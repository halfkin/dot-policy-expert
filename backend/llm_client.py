"""OpenRouter LLM interaction."""
from __future__ import annotations

import os
from typing import List, Optional, Tuple

import requests
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini").strip()
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
COMPANY_NAME = os.getenv("COMPANY_NAME", "Loomo")
BOT_NAME = os.getenv("BOT_NAME", "Dot")


def call_openrouter(
    question: str,
    sources: List[Tuple[float, str, str, str]],
    history: Optional[list] = None,
) -> str:
    """
    sources: list of (normalized_score, doc_id, chunk_id, chunk_text)
    """
    sources_block = "\n\n".join(
        [
            f"[rank={idx} score={score:.3f} | {doc_id} | {chunk_id}]\n{chunk_text}"
            for idx, (score, doc_id, chunk_id, chunk_text) in enumerate(sources, start=1)
        ]
    )

    system = (
        f"You are {BOT_NAME}, {COMPANY_NAME}'s policy assistant. You answer questions using ONLY the provided SOURCES.\n"
        "Read ALL provided source chunks before answering.\n"
        "\n"
        "ANSWERING RULES:\n"
        "- If the source chunks contain information that answers the question, write a clear, direct answer in your own words, then cite the source(s) you used.\n"
        "- Do NOT simply list or paste the source chunks. Synthesize the information into a helpful response.\n"
        "- If the question requires reasoning (e.g., 'Am I eligible on day 29?'), apply the policy rules to the specific situation and give a direct yes/no answer with explanation.\n"
        "- If the source chunks do NOT contain information that directly answers the question, respond with exactly: Not in sources. I'd recommend reaching out to our support team for clarification.\n"
        "- A chunk is NOT relevant just because it shares a keyword. A chunk about enforcement policies does not answer a question about conversation history. A chunk about onboarding does not answer a question about stock tickers.\n"
        "\n"
        "NEVER DO:\n"
        "- Do NOT ask follow-up questions.\n"
        "- Do NOT guess or infer facts not in the sources.\n"
        "- Do NOT use outside knowledge.\n"
        "- Do NOT answer meta-questions about your own system, documents, or capabilities.\n"
    )

    history_lines: List[str] = []
    for turn in history or []:
        role = "User" if getattr(turn, "role", None) == "user" else "Assistant"
        content = (getattr(turn, "content", "") or "").strip()
        if not content:
            continue
        history_lines.append(f"{role}: {content}")
    history_block = "\n".join(history_lines) if history_lines else "(none)"

    user = (
        "CONVERSATION HISTORY:\n"
        f"{history_block}\n\n"
        f"CURRENT QUESTION:\n{question}\n\n"
        "SOURCES (Top-K retrieved chunks):\n"
        f"{sources_block}\n"
    )

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
    }

    r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=20)
    if not r.ok:
        raise RuntimeError(f"OpenRouter HTTP {r.status_code}: {r.text[:500]}")
    data = r.json()
    return data["choices"][0]["message"]["content"].strip()
