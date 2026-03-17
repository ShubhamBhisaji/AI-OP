"""
models/pipeline.py — Lightweight ML pipeline for task-complexity scoring.

Provides two simple public functions:

    load_model()        Load (or auto-create) the sklearn pipeline from
                        models/model.pkl.  Cached after first call.

    predict(text)       Run inference on a task description string.
                        Returns a dict:
                          {
                            "label":       "SIMPLE" | "MODERATE" | "COMPLEX",
                            "confidence":  float (0.0 – 1.0),
                            "scores":      {"SIMPLE": float, "MODERATE": float, "COMPLEX": float}
                          }

The model is a scikit-learn Pipeline:
    TfidfVectorizer  →  LogisticRegression (multi-class, one-vs-rest)

The ModelRouter uses predict() for cost-free offline complexity scoring,
falling back to heuristic if the model file is absent.

Regenerate the model at any time:
    python models/train_model.py
"""

from __future__ import annotations

import logging
import os
import pickle
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # sklearn types for static checkers only

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────
_HERE     = Path(__file__).resolve().parent
_PKL_PATH = _HERE / "model.pkl"

# ── Labels ────────────────────────────────────────────────────────────────
LABELS = ["SIMPLE", "MODERATE", "COMPLEX"]

# ── Module-level cache ─────────────────────────────────────────────────────
_model = None


def load_model():
    """
    Load the sklearn pipeline from models/model.pkl.

    If the file does not exist, auto-trains and saves a default model so
    the system works out-of-the-box without a separate setup step.

    Returns the loaded sklearn Pipeline object.
    The result is cached in memory after the first call.
    """
    global _model
    if _model is not None:
        return _model

    if not _PKL_PATH.exists():
        logger.info("models/model.pkl not found — training default model...")
        _train_default()

    with open(_PKL_PATH, "rb") as f:
        _model = pickle.load(f)

    logger.info("models/model.pkl loaded (classes=%s)", list(getattr(_model, "classes_", LABELS)))
    return _model


def predict(text: str) -> dict:
    """
    Predict the complexity of a task description.

    Parameters
    ----------
    text : str
        A task description or prompt, e.g.
        "What is 2+2?" or "Build a full-stack SaaS platform with OAuth."

    Returns
    -------
    dict with keys:
        label      : "SIMPLE" | "MODERATE" | "COMPLEX"
        confidence : float — probability of the predicted class
        scores     : dict mapping each label to its probability
    """
    if not isinstance(text, str) or not text.strip():
        return {"label": "MODERATE", "confidence": 0.5, "scores": {l: 0.33 for l in LABELS}}

    model = load_model()

    proba  = model.predict_proba([text])[0]          # shape: (n_classes,)
    classes = list(model.classes_)
    idx     = int(proba.argmax())
    label   = classes[idx]
    conf    = float(proba[idx])

    scores = {cls: round(float(p), 4) for cls, p in zip(classes, proba)}

    return {
        "label":      label,
        "confidence": round(conf, 4),
        "scores":     scores,
    }


# ── Seed training corpus ─────────────────────────────────────────────────
# Representative hand-labelled examples.  Expand via models/train_model.py.
_SEED: list[tuple[str, str]] = [
        # SIMPLE
        ("What is 2 + 2?",                                             "SIMPLE"),
        ("What day is it today?",                                      "SIMPLE"),
        ("Translate 'hello' to Spanish.",                              "SIMPLE"),
        ("What is the capital of France?",                             "SIMPLE"),
        ("Give me a synonym for 'happy'.",                             "SIMPLE"),
        ("Write a one-sentence bio for Einstein.",                     "SIMPLE"),
        ("What is Python?",                                            "SIMPLE"),
        ("List the planets in the solar system.",                      "SIMPLE"),
        ("Define 'machine learning'.",                                 "SIMPLE"),
        ("What is the boiling point of water?",                       "SIMPLE"),
        ("Convert 100 USD to EUR.",                                    "SIMPLE"),
        ("Summarise this paragraph in one sentence.",                  "SIMPLE"),
        ("Is the sky blue?",                                           "SIMPLE"),
        ("What are the primary colours?",                              "SIMPLE"),
        ("Tell me a joke.",                                            "SIMPLE"),

        # MODERATE
        ("Write a Python function to sort a list of dictionaries.",    "MODERATE"),
        ("Summarise the key benefits of microservices architecture.",  "MODERATE"),
        ("Draft a 200-word blog intro about remote work trends.",      "MODERATE"),
        ("Create a regex that validates email addresses.",             "MODERATE"),
        ("Explain the difference between REST and GraphQL.",           "MODERATE"),
        ("Write unit tests for a login function.",                     "MODERATE"),
        ("Analyse these 10 customer reviews and categorise sentiment.","MODERATE"),
        ("Refactor this 50-line Python class to use dataclasses.",     "MODERATE"),
        ("Build a simple CLI argument parser with argparse.",          "MODERATE"),
        ("Write a SQL query to find the top 5 customers by revenue.",  "MODERATE"),
        ("Create a markdown report summarising Q3 metrics.",           "MODERATE"),
        ("Generate a landing page copy for a fitness app.",            "MODERATE"),
        ("Describe the CAP theorem with a short example.",             "MODERATE"),
        ("Write a Dockerfile for a FastAPI application.",              "MODERATE"),
        ("Extract all dates from this legal document.",                "MODERATE"),

        # COMPLEX
        ("Design and build a full-stack SaaS platform with OAuth.",    "COMPLEX"),
        ("Build a multi-agent research pipeline with memory and tools.","COMPLEX"),
        ("Create an end-to-end ML pipeline with training and serving.","COMPLEX"),
        ("Architect a real-time event-driven microservices system.",   "COMPLEX"),
        ("Build a Kubernetes-deployed Python service with CI/CD.",     "COMPLEX"),
        ("Develop a RAG system over a 50k document corpus.",           "COMPLEX"),
        ("Write and benchmark three sorting algorithms at scale.",     "COMPLEX"),
        ("Build an autonomous web scraping and analysis agent.",       "COMPLEX"),
        ("Design a zero-downtime database migration strategy.",        "COMPLEX"),
        ("Build a distributed task queue with retry and dead-letter.", "COMPLEX"),
        ("Implement a self-healing orchestration layer for agents.",   "COMPLEX"),
        ("Create a model fine-tuning pipeline with eval benchmarks.",  "COMPLEX"),
        ("Develop a production-grade authentication system with 2FA.", "COMPLEX"),
        ("Build a real-time collaborative document editor backend.",   "COMPLEX"),
        ("Architect and code a multi-tenant billing engine.",          "COMPLEX"),
]


# ── Default model training ─────────────────────────────────────────────────

def _train_default() -> None:
    """
    Train a minimal TF-IDF + LogisticRegression classifier on the seed
    corpus and save to models/model.pkl.  Runs in under a second with no GPU.
    Run models/train_model.py to retrain on a larger dataset.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    texts  = [t for t, _ in _SEED]
    labels = [l for _, l in _SEED]

    model = Pipeline([
        ("tfidf", TfidfVectorizer(
            ngram_range=(1, 2),
            max_features=5_000,
            sublinear_tf=True,
        )),
        ("clf", LogisticRegression(
            max_iter=500,
            C=1.0,
            solver="lbfgs",
        )),
    ])
    model.fit(texts, labels)

    _PKL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_PKL_PATH, "wb") as f:
        pickle.dump(model, f, protocol=pickle.HIGHEST_PROTOCOL)

    logger.info("Default model saved → %s", _PKL_PATH)
