"""Language detection and translation."""
from __future__ import annotations

import os
import re
from typing import Optional

import requests

from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

SUPPORTED_LANGUAGES = {"en", "fr", "es"}

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini").strip()
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

try:
    from langdetect import detect, detect_langs, LangDetectException, DetectorFactory
    DetectorFactory.seed = 0
    HAS_LANGDETECT = True
except ImportError:
    detect = None  # type: ignore[assignment]
    detect_langs = None  # type: ignore[assignment]
    LangDetectException = Exception  # type: ignore[assignment]
    HAS_LANGDETECT = False


def check_language(text: str) -> Optional[str]:
    sample = (text or "").strip()
    if len(sample) < 10:
        return None
    if not HAS_LANGDETECT:
        lowered = sample.lower()
        if re.search(r"[¿¡]", sample) or re.search(
            r"\b(hola|gracias|reembolso|politica|política|cuenta|factura)\b", lowered
        ):
            return "es"
        if re.search(r"\b(bonjour|merci|remboursement|politique|facturation|est-ce|quelle|rgpd|conforme|combien|quels?|cette|nous|vous|notre|votre)\b", lowered):
            return "fr"
        if re.search(r"\b(bitte|danke|rückerstattung|richtlinie|vertrag|kündigung|zahlung|wie|warum|welche|unser|dieser)\b", lowered):
            return "de"
        if re.search(r"[\u4e00-\u9fff]", sample):
            return "zh"
        if re.search(r"[\uac00-\ud7af]", sample):
            return "ko"
        return None
    try:
        ranked = detect_langs(sample) if detect_langs else []  # type: ignore[misc]
        if ranked:
            best = ranked[0]
            lang = getattr(best, "lang", None)
            prob = float(getattr(best, "prob", 0.0))
            if lang == "en":
                return "en"
            if prob >= 0.90:
                return lang
            return None
        return detect(sample)  # type: ignore[misc]
    except LangDetectException:
        return None


def translate_to_english(text: str, source_lang: str) -> str:
    """Translate French or Spanish input to English using OpenRouter."""
    if source_lang == "en":
        return text
    if source_lang not in {"fr", "es"}:
        raise ValueError(f"Unsupported translation source language: {source_lang}")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a translator. Translate the following text to English. "
                    "Return ONLY the translation, nothing else."
                ),
            },
            {"role": "user", "content": text},
        ],
        "temperature": 0.0,
    }
    response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=20)
    if not response.ok:
        raise RuntimeError(f"Translation request failed: HTTP {response.status_code}")
    data = response.json()
    translated = data["choices"][0]["message"]["content"].strip()
    if not translated:
        raise RuntimeError("Translation response was empty")
    return translated
