"""
nlp_tool.py — Production NLP tool for AetheerAI agents.

Provides seven NLP capabilities through a single unified entry point:

  sentiment   — Positive / Negative / Neutral classification with confidence.
  ner         — Named Entity Recognition (extract people, orgs, locations, dates …).
  classify    — Zero-shot text classification into caller-supplied categories.
  summarize   — Abstractive summary with configurable max length.
  qa          — Extractive question-answering over a supplied context passage.
  translate   — Language detection + translation (requires transformers pipeline).
  embed       — Return a fixed-length text embedding vector (sentence-transformers).

Provider auto-selection strategy
---------------------------------
Each action tries the following in order, falling back gracefully:

  1. HuggingFace Transformers (local, offline) — best quality, no API cost,
     requires: pip install transformers torch   (or transformers tensorflow)
  2. OpenAI via litellm / AIAdapter — if OPENAI_API_KEY is set.
  3. GitHub Models (free GPT-4.1) — if GITHUB_TOKEN is set.
  4. Rule-based fallback — lightweight regex / lexicon approach.
     Always available, zero dependencies. Quality is basic but never fails.

Typical usage inside an agent:
    from tools.nlp_tool import nlp_tool

    result = nlp_tool(action="sentiment", text="I absolutely love this product!")
    # → "Sentiment: POSITIVE (confidence: 0.98)"

    result = nlp_tool(action="ner", text="Elon Musk founded SpaceX in 2002.")
    # → "Entities: PERSON: Elon Musk | ORG: SpaceX | DATE: 2002"

    result = nlp_tool(action="classify",
                      text="Breaking: New AI chip announced",
                      labels=["technology", "sports", "politics"])
    # → "Class: technology (score: 0.93)"

    result = nlp_tool(action="summarize",
                      text="...<long article>...",
                      max_length=100)
    # → "Summary: ..."

    result = nlp_tool(action="qa",
                      text="The Eiffel Tower was built in 1889 by Gustave Eiffel.",
                      question="Who built the Eiffel Tower?")
    # → "Answer: Gustave Eiffel (score: 0.97)"
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy HuggingFace Transformers helpers
# ---------------------------------------------------------------------------

_HF_PIPELINES: dict[str, Any] = {}   # cache loaded HF pipelines


def _hf_available() -> bool:
    try:
        import transformers  # type: ignore[import-not-found]  # noqa: F401
        return True
    except ImportError:
        return False


def _get_hf_pipeline(task: str, model: str | None = None):
    """Load and cache a HuggingFace transformers pipeline."""
    from transformers import pipeline as hf_pipeline  # type: ignore

    key = f"{task}:{model or 'default'}"
    if key not in _HF_PIPELINES:
        kwargs: dict[str, Any] = {"task": task}
        if model:
            kwargs["model"] = model
        try:
            _HF_PIPELINES[key] = hf_pipeline(**kwargs)
            logger.info("nlp_tool: loaded HF pipeline task='%s' model='%s'.", task, model)
        except Exception as exc:
            logger.warning("nlp_tool: HF pipeline '%s' failed to load: %s", task, exc)
            raise
    return _HF_PIPELINES[key]


# ---------------------------------------------------------------------------
# LLM helper (litellm / AIAdapter fallback)
# ---------------------------------------------------------------------------

def _llm_chat(prompt: str) -> str:
    """
    Send a prompt to the first available cloud LLM.
    Returns the reply string, or raises RuntimeError if no provider available.
    """
    import sys, os  # noqa: E401
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from ai.ai_adapter import AIAdapter, SUPPORTED_PROVIDERS

    # Pick the first provider with a valid key
    key_map = {
        "openai":  "OPENAI_API_KEY",
        "claude":  "ANTHROPIC_API_KEY",
        "gemini":  "GEMINI_API_KEY",
        "github":  "GITHUB_TOKEN",
    }
    for prov, env in key_map.items():
        if os.environ.get(env, "").strip():
            adapter = AIAdapter(provider=prov)
            return adapter.chat([{"role": "user", "content": prompt}])

    raise RuntimeError("No LLM provider available (no API keys set).")


# ---------------------------------------------------------------------------
# ── Sentiment ──────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

_POSITIVE_WORDS = {
    "good","great","excellent","amazing","wonderful","fantastic","love","best",
    "better","happy","positive","success","win","perfect","brilliant","outstanding",
    "superb","awesome","stellar","joy","glad","thrilled","excited","delighted",
    "pleased","satisfied","lovely","nice","beautiful","fabulous","magnificent",
}
_NEGATIVE_WORDS = {
    "bad","terrible","awful","horrible","worst","hate","failure","poor","negative",
    "wrong","error","broken","fail","issue","problem","difficult","hard","impossible",
    "never","sad","angry","upset","disappointed","frustrating","annoyed","useless",
    "pathetic","dreadful","disaster","horrible","appalling","disgusting","inferior",
}


def _sentiment_lexicon(text: str) -> str:
    words = re.findall(r"\b[a-z]+\b", text.lower())
    pos = sum(1 for w in words if w in _POSITIVE_WORDS)
    neg = sum(1 for w in words if w in _NEGATIVE_WORDS)
    total = max(pos + neg, 1)
    if pos > neg:
        return f"Sentiment: POSITIVE (confidence: {pos/total:.2f}) [lexicon fallback]"
    if neg > pos:
        return f"Sentiment: NEGATIVE (confidence: {neg/total:.2f}) [lexicon fallback]"
    return "Sentiment: NEUTRAL (confidence: 0.50) [lexicon fallback]"


def _action_sentiment(text: str) -> str:
    # 1. HuggingFace
    if _hf_available():
        try:
            pipe = _get_hf_pipeline("sentiment-analysis")
            result = pipe(text[:512])[0]
            label = result["label"].upper()
            score = round(result["score"], 4)
            return f"Sentiment: {label} (confidence: {score})"
        except Exception as exc:
            logger.debug("HF sentiment failed: %s", exc)

    # 2. LLM
    try:
        prompt = (
            f"Classify the sentiment of the following text as POSITIVE, NEGATIVE, or NEUTRAL.\n"
            f"Reply with exactly: SENTIMENT: <label> (confidence: <0.00–1.00>)\n\n"
            f"Text: {text[:1000]}"
        )
        raw = _llm_chat(prompt)
        m = re.search(r"SENTIMENT:\s*(POSITIVE|NEGATIVE|NEUTRAL)\s*\(confidence:\s*([0-9.]+)\)", raw, re.I)
        if m:
            return f"Sentiment: {m.group(1).upper()} (confidence: {m.group(2)})"
        return f"Sentiment: {raw.strip()}"
    except Exception as exc:
        logger.debug("LLM sentiment failed: %s", exc)

    # 3. Lexicon fallback
    return _sentiment_lexicon(text)


# ---------------------------------------------------------------------------
# ── Named Entity Recognition ───────────────────────────────────────────────
# ---------------------------------------------------------------------------

_NER_PATTERNS = [
    (r"\b[A-Z][a-z]+ (?:[A-Z][a-z]+ )*[A-Z][a-z]+\b", "PERSON"),   # Multi-word proper names
    (r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b", "DATE"),
    (r"\b\d{4}\b", "DATE"),
    (r"\$\s*[\d,]+(?:\.\d{2})?(?:\s*(?:million|billion|trillion))?\b", "MONEY"),
    (r"\b\d+(?:\.\d+)?\s*(?:percent|%)\b", "PERCENT"),
    (r"\b(?:Inc\.|LLC|Ltd\.|Corp\.|Corporation|Company|Technologies|Systems|Group|Foundation)\b", "ORG"),
]


def _ner_regex(text: str) -> str:
    found: list[str] = []
    for pattern, label in _NER_PATTERNS:
        for m in re.finditer(pattern, text):
            found.append(f"{label}: {m.group().strip()}")
    if not found:
        return "Entities: None detected [regex fallback]"
    return "Entities: " + " | ".join(dict.fromkeys(found))  # deduplicate, preserve order


def _action_ner(text: str) -> str:
    # 1. HuggingFace
    if _hf_available():
        try:
            pipe = _get_hf_pipeline("ner", model="dslim/bert-base-NER")
            entities = pipe(text[:512])
            if entities:
                grouped: dict[str, list[str]] = {}
                for ent in entities:
                    lbl = ent["entity_group"] if "entity_group" in ent else ent["entity"].lstrip("BI-")
                    grouped.setdefault(lbl, []).append(ent["word"])
                parts = [f"{lbl}: {', '.join(dict.fromkeys(ws))}" for lbl, ws in grouped.items()]
                return "Entities: " + " | ".join(parts)
            return "Entities: None detected"
        except Exception as exc:
            logger.debug("HF NER failed: %s", exc)

    # 2. LLM
    try:
        prompt = (
            f"Extract named entities from the text below.\n"
            f"Format EXACTLY as: ENTITY_TYPE: entity_text (repeat for each entity, pipe-separated on one line).\n"
            f"Entity types: PERSON, ORG, LOCATION, DATE, MONEY, PRODUCT, EVENT\n\n"
            f"Text: {text[:1000]}\n\n"
            f"Entities:"
        )
        raw = _llm_chat(prompt)
        return f"Entities: {raw.strip()}"
    except Exception as exc:
        logger.debug("LLM NER failed: %s", exc)

    # 3. Regex fallback
    return _ner_regex(text)


# ---------------------------------------------------------------------------
# ── Zero-shot Classification ───────────────────────────────────────────────
# ---------------------------------------------------------------------------

def _action_classify(text: str, labels: list[str]) -> str:
    if not labels:
        return "Error: 'labels' list is required for classify action."

    # 1. HuggingFace zero-shot
    if _hf_available():
        try:
            pipe = _get_hf_pipeline(
                "zero-shot-classification",
                model="facebook/bart-large-mnli",
            )
            result = pipe(text[:512], candidate_labels=labels)
            best_label = result["labels"][0]
            best_score = round(result["scores"][0], 4)
            all_scores = ", ".join(
                f"{l}: {s:.3f}" for l, s in zip(result["labels"], result["scores"])
            )
            return f"Class: {best_label} (score: {best_score})\nAll scores: {all_scores}"
        except Exception as exc:
            logger.debug("HF zero-shot classification failed: %s", exc)

    # 2. LLM
    try:
        label_list = ", ".join(f'"{l}"' for l in labels)
        prompt = (
            f"Classify the following text into exactly ONE of these categories: {label_list}.\n"
            f"Reply with: CLASS: <category> (score: <0.00–1.00>)\n\n"
            f"Text: {text[:1000]}"
        )
        raw = _llm_chat(prompt)
        m = re.search(r"CLASS:\s*(.+?)\s*\(score:\s*([0-9.]+)\)", raw, re.I)
        if m:
            return f"Class: {m.group(1).strip()} (score: {m.group(2)})"
        return f"Class: {raw.strip()}"
    except Exception as exc:
        logger.debug("LLM classification failed: %s", exc)

    # 3. Keyword overlap fallback
    text_lower = text.lower()
    scores = {l: text_lower.count(l.lower()) for l in labels}
    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    return f"Class: {best} (score: N/A) [keyword fallback]"


# ---------------------------------------------------------------------------
# ── Summarization ─────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

def _action_summarize(text: str, max_length: int = 150) -> str:
    max_length = max(30, min(max_length, 512))

    # 1. HuggingFace
    if _hf_available():
        try:
            pipe = _get_hf_pipeline("summarization", model="facebook/bart-large-cnn")
            word_count = len(text.split())
            min_len = min(30, max(10, word_count // 10))
            result = pipe(
                text[:4096],
                max_length=max_length,
                min_length=min_len,
                do_sample=False,
            )
            return "Summary: " + result[0]["summary_text"]
        except Exception as exc:
            logger.debug("HF summarization failed: %s", exc)

    # 2. LLM
    try:
        prompt = (
            f"Summarize the following text in at most {max_length} words. "
            f"Be concise and preserve the key facts.\n\n"
            f"Text:\n{text[:3000]}\n\nSummary:"
        )
        raw = _llm_chat(prompt)
        return f"Summary: {raw.strip()}"
    except Exception as exc:
        logger.debug("LLM summarization failed: %s", exc)

    # 3. Extractive fallback — return first N sentences
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    words, chosen = 0, []
    for s in sentences:
        w = len(s.split())
        if words + w > max_length:
            break
        chosen.append(s)
        words += w
    return "Summary: " + " ".join(chosen or sentences[:3]) + " [extractive fallback]"


# ---------------------------------------------------------------------------
# ── Extractive Question Answering ─────────────────────────────────────────
# ---------------------------------------------------------------------------

def _action_qa(text: str, question: str) -> str:
    if not question:
        return "Error: 'question' is required for the qa action."

    # 1. HuggingFace
    if _hf_available():
        try:
            pipe = _get_hf_pipeline("question-answering")
            result = pipe(question=question, context=text[:4096])
            answer = result["answer"]
            score  = round(result["score"], 4)
            return f"Answer: {answer} (confidence: {score})"
        except Exception as exc:
            logger.debug("HF QA failed: %s", exc)

    # 2. LLM
    try:
        prompt = (
            f"Answer the question below using ONLY the provided context.\n"
            f"Reply with: ANSWER: <answer> (confidence: <0.00–1.00>)\n\n"
            f"Context: {text[:2000]}\n\n"
            f"Question: {question}"
        )
        raw = _llm_chat(prompt)
        m = re.search(r"ANSWER:\s*(.+?)\s*\(confidence:\s*([0-9.]+)\)", raw, re.I)
        if m:
            return f"Answer: {m.group(1).strip()} (confidence: {m.group(2)})"
        return f"Answer: {raw.strip()}"
    except Exception as exc:
        logger.debug("LLM QA failed: %s", exc)

    # 3. Keyword search fallback
    sentences = re.split(r"(?<=[.!?])\s+", text)
    qwords = set(re.findall(r"\b\w+\b", question.lower()))
    best_sent, best_score = "", 0
    for s in sentences:
        swords = set(re.findall(r"\b\w+\b", s.lower()))
        overlap = len(qwords & swords)
        if overlap > best_score:
            best_score, best_sent = overlap, s
    if best_sent:
        return f"Answer: {best_sent} [extractive fallback]"
    return "Answer: No relevant information found in the provided context."


# ---------------------------------------------------------------------------
# ── Translation ───────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

def _action_translate(text: str, target_lang: str = "en") -> str:
    target_lang = (target_lang or "en").strip().lower()

    # 1. HuggingFace (Helsinki-NLP opus-mt models)
    if _hf_available():
        try:
            hf_task = f"translation_xx_to_yy"
            model_name = f"Helsinki-NLP/opus-mt-mul-{target_lang}"
            pipe = _get_hf_pipeline("translation", model=model_name)
            result = pipe(text[:512])
            translated = result[0]["translation_text"]
            return f"Translation ({target_lang}): {translated}"
        except Exception as exc:
            logger.debug("HF translation failed: %s", exc)

    # 2. LLM
    try:
        prompt = (
            f"Translate the following text to {target_lang} (ISO 639-1 code). "
            f"Return ONLY the translated text, nothing else.\n\n"
            f"Text: {text[:2000]}"
        )
        raw = _llm_chat(prompt)
        return f"Translation ({target_lang}): {raw.strip()}"
    except Exception as exc:
        logger.debug("LLM translation failed: %s", exc)

    return f"Error: Translation is not available. Install transformers or configure an API key."


# ---------------------------------------------------------------------------
# ── Text Embedding ────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

def _action_embed(text: str) -> str:
    # 1. sentence-transformers
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        model = _HF_PIPELINES.setdefault(
            "__sentence_transformer",
            SentenceTransformer("all-MiniLM-L6-v2"),
        )
        vec = model.encode(text).tolist()
        preview = [round(v, 4) for v in vec[:8]]
        return (
            f"Embedding: dim={len(vec)}, "
            f"preview={preview} … "
            f"(use embed action programmatically for the full vector)"
        )
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("sentence-transformers embed failed: %s", exc)

    # 2. OpenAI embeddings via LLM adapter
    try:
        import litellm as _ll  # type: ignore
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if openai_key:
            resp = _ll.embedding(model="text-embedding-3-small", input=[text])
            vec = resp["data"][0]["embedding"]
            preview = [round(v, 4) for v in vec[:8]]
            return f"Embedding (OpenAI): dim={len(vec)}, preview={preview} …"
    except Exception as exc:
        logger.debug("OpenAI embedding failed: %s", exc)

    return (
        "Error: Embedding requires sentence-transformers or an OpenAI API key.\n"
        "Install with: pip install sentence-transformers"
    )


# ---------------------------------------------------------------------------
# ── Main entry point ──────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

def nlp_tool(
    action: str = "sentiment",
    text: str = "",
    labels: list[str] | None = None,
    question: str = "",
    max_length: int = 150,
    target_lang: str = "en",
) -> str:
    """
    Unified NLP tool for AetheerAI agents.

    Parameters
    ----------
    action      : sentiment | ner | classify | summarize | qa | translate | embed
    text        : Input text to process.
    labels      : Category list for 'classify' action.
    question    : Question string for 'qa' action.
    max_length  : Max word/token length for 'summarize' output.
    target_lang : ISO 639-1 target language code for 'translate' (default 'en').

    Returns a human-readable string result.
    """
    if not isinstance(text, str) or not text.strip():
        return "Error: 'text' must be a non-empty string."

    action = (action or "sentiment").strip().lower()

    if action == "sentiment":
        return _action_sentiment(text)
    if action == "ner":
        return _action_ner(text)
    if action == "classify":
        return _action_classify(text, labels or [])
    if action == "summarize":
        return _action_summarize(text, max_length=max_length)
    if action == "qa":
        return _action_qa(text, question)
    if action == "translate":
        return _action_translate(text, target_lang=target_lang)
    if action == "embed":
        return _action_embed(text)

    return (
        f"Unknown action '{action}'. "
        "Valid actions: sentiment, ner, classify, summarize, qa, translate, embed."
    )
