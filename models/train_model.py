"""
models/train_model.py — Train and save models/model.pkl.

Run this whenever you want to retrain on a larger or updated dataset:

    python models/train_model.py
    python models/train_model.py --data path/to/tasks.csv
    python models/train_model.py --eval   # print accuracy on a held-out split

CSV format (if --data is used):
    text,label
    "What is 2+2?",SIMPLE
    "Build a SaaS platform",COMPLEX
    ...

Labels must be: SIMPLE | MODERATE | COMPLEX
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import pickle
import sys
from pathlib import Path

# Allow running from any working directory
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="[train] %(message)s")
logger = logging.getLogger(__name__)

_HERE     = Path(__file__).resolve().parent
_PKL_PATH = _HERE / "model.pkl"
LABELS    = ["SIMPLE", "MODERATE", "COMPLEX"]


def build_pipeline():
    """Return an untrained sklearn Pipeline (TF-IDF → LogisticRegression)."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    return Pipeline([
        ("tfidf", TfidfVectorizer(
            ngram_range=(1, 2),
            max_features=10_000,
            sublinear_tf=True,
            strip_accents="unicode",
        )),
        ("clf", LogisticRegression(
            max_iter=1_000,
            C=1.0,
            solver="lbfgs",
            class_weight="balanced",
        )),
    ])


def load_csv(path: str) -> tuple[list[str], list[str]]:
    """Load a two-column CSV with headers 'text' and 'label'."""
    texts, labels = [], []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, 1):
            text  = (row.get("text") or "").strip()
            label = (row.get("label") or "").strip().upper()
            if not text:
                logger.warning("Row %d: empty text — skipped", i)
                continue
            if label not in LABELS:
                logger.warning("Row %d: unknown label '%s' — skipped", i, label)
                continue
            texts.append(text)
            labels.append(label)
    return texts, labels


def _seed_data() -> tuple[list[str], list[str]]:
    """Return the built-in seed corpus (same as pipeline.py auto-train)."""
    from models.pipeline import _SEED  # type: ignore[attr-defined]  # noqa: PLC0415
    return [t for t, _ in _SEED], [l for _, l in _SEED]


def train(
    texts: list[str],
    labels: list[str],
    *,
    evaluate: bool = False,
) -> object:
    """
    Fit the pipeline, optionally print accuracy, and save models/model.pkl.

    Returns the trained sklearn Pipeline.
    """
    if not texts:
        raise ValueError("No training examples provided.")

    label_counts = {l: labels.count(l) for l in LABELS}
    logger.info("Training set: %d examples — %s", len(texts), label_counts)

    if evaluate:
        from sklearn.model_selection import cross_val_score
        model = build_pipeline()
        scores = cross_val_score(model, texts, labels, cv=min(5, len(texts) // 3), scoring="accuracy")
        logger.info("Cross-val accuracy: %.3f ± %.3f", scores.mean(), scores.std())

    model = build_pipeline()
    model.fit(texts, labels)

    _PKL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_PKL_PATH, "wb") as f:
        pickle.dump(model, f, protocol=pickle.HIGHEST_PROTOCOL)

    logger.info("Saved → %s  (%d bytes)", _PKL_PATH, _PKL_PATH.stat().st_size)
    return model


def main() -> None:
    parser = argparse.ArgumentParser(description="Train models/model.pkl")
    parser.add_argument("--data",  default=None, help="Path to training CSV (text,label)")
    parser.add_argument("--eval",  action="store_true", help="Print cross-val accuracy")
    args = parser.parse_args()

    if args.data:
        logger.info("Loading training data from %s ...", args.data)
        texts, labels = load_csv(args.data)
    else:
        logger.info("No --data supplied — using built-in seed corpus.")
        from models.pipeline import _SEED  # noqa: PLC0415  (module-level constant)
        texts  = [t for t, _ in _SEED]
        labels = [l for _, l in _SEED]

    train(texts, labels, evaluate=args.eval)

    # Quick smoke-test
    from models.pipeline import predict, _model  # noqa: PLC0415
    import models.pipeline as _mp
    _mp._model = None          # force reload from the new file
    test_cases = [
        ("What is 2+2?",                            "SIMPLE"),
        ("Write a Python sort function.",            "MODERATE"),
        ("Build a full-stack SaaS with OAuth.",      "COMPLEX"),
    ]
    print("\nSmoke test:")
    for text, expected in test_cases:
        result = predict(text)
        match  = "✓" if result["label"] == expected else "✗"
        print(f"  {match} [{result['label']:8s} / {result['confidence']:.2f}]  {text[:50]}")


if __name__ == "__main__":
    main()
