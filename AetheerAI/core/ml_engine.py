"""
ml_engine.py — Scikit-learn backed ML Prediction Engine for AetheerAI.

Provides a complete machine-learning pipeline with:

  Training   — Fit classification, regression, or clustering models on
               numeric or raw-text feature sets.
  Prediction — Run inference (with optional probability scores) through
               a fully restored sklearn Pipeline.
  Evaluation — Accuracy / F1 / R² / RMSE metrics computed on a hold-out
               split automatically created at training time.
  Persistence — Save / load any trained model as a .pkl checkpoint via
               joblib (handles numpy arrays far better than stdlib pickle).
               Models are auto-loaded from disk on first predict call.

Supported input types
---------------------
  Numeric  (list[list[float|int]])  → StandardScaler → algorithm
  Text     (list[str])              → TfidfVectorizer → algorithm
  Mixed    (list[dict])             → ColumnTransformer → algorithm

Supported tasks
---------------
  classification  — RandomForest (default), LogisticRegression, SVC,
                    GradientBoosting, NaiveBayes (text only)
  regression      — RandomForest (default), Ridge, GradientBoosting,
                    LinearRegression
  clustering      — KMeans (default), DBSCAN (no labels needed)

Minimal usage
-------------
    engine = MLEngine.load_or_create()

    # Text classification (e.g. spam detection):
    engine.train(
        "spam",
        features=["Buy now!", "Hello", "Win $1 000 000"],
        labels=[1, 0, 1],
        task="classification",
    )
    print(engine.predict("spam", ["Claim your prize!"]))  # [1]

    # Numeric regression:
    engine.train(
        "house-price",
        features=[[3,2,1500],[4,3,2100],[2,1,900]],
        labels=[250000, 380000, 145000],
        task="regression",
    )
    print(engine.predict("house-price", [[3,2,1400]]))    # [~240000]

    # Persist / restore:
    engine.save("spam")
    engine.load("spam")          # or use load_or_create() on next run
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency imports — fail gracefully with a clear message
# ---------------------------------------------------------------------------

def _require_sklearn() -> Any:
    try:
        import sklearn  # noqa: F401
        return sklearn
    except ImportError as exc:
        raise ImportError(
            "scikit-learn is required for ML predictions.\n"
            "Install it with: pip install scikit-learn"
        ) from exc


def _joblib():
    try:
        import joblib  # noqa: PLC0415 — bundled with scikit-learn
        return joblib
    except ImportError as exc:
        raise ImportError(
            "joblib is required for model persistence.\n"
            "It is bundled with scikit-learn: pip install scikit-learn"
        ) from exc


# ---------------------------------------------------------------------------
# Storage location
# ---------------------------------------------------------------------------

def _models_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent / "aetheerai_data"
    else:
        base = Path(__file__).parent.parent / "memory"
    d = base / "ml_models"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Internal helpers — feature type detection & pipeline builders
# ---------------------------------------------------------------------------

def _detect_feature_type(features: list) -> str:
    """Return 'text', 'numeric', or 'mixed-dict'."""
    if not features:
        raise ValueError("features list is empty.")
    first = features[0]
    if isinstance(first, str):
        return "text"
    if isinstance(first, dict):
        return "mixed-dict"
    return "numeric"


def _build_classification_pipeline(feature_type: str, algorithm: str):
    """Return an unfitted sklearn Pipeline for classification."""
    _require_sklearn()
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.naive_bayes import MultinomialNB, ComplementNB
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVC
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.feature_extraction import DictVectorizer

    alg = algorithm.lower()

    if feature_type == "text":
        vectorizer = TfidfVectorizer(
            max_features=20_000,
            ngram_range=(1, 2),
            sublinear_tf=True,
            strip_accents="unicode",
        )
        if alg in ("auto", "random_forest"):
            clf = RandomForestClassifier(n_estimators=200, n_jobs=-1, random_state=42)
        elif alg == "logistic_regression":
            clf = LogisticRegression(max_iter=1000, C=1.0)
        elif alg == "naive_bayes":
            clf = ComplementNB(alpha=0.1)
        elif alg == "gradient_boosting":
            clf = GradientBoostingClassifier(n_estimators=100, random_state=42)
        elif alg == "svc":
            clf = SVC(kernel="linear", probability=True, C=1.0)
        else:
            clf = RandomForestClassifier(n_estimators=200, n_jobs=-1, random_state=42)
        return Pipeline([("tfidf", vectorizer), ("clf", clf)])

    if feature_type == "mixed-dict":
        vec = DictVectorizer(sparse=False)
        scaler = StandardScaler()
        if alg in ("auto", "random_forest"):
            clf = RandomForestClassifier(n_estimators=200, n_jobs=-1, random_state=42)
        elif alg == "logistic_regression":
            clf = LogisticRegression(max_iter=1000)
        elif alg == "gradient_boosting":
            clf = GradientBoostingClassifier(n_estimators=100, random_state=42)
        else:
            clf = RandomForestClassifier(n_estimators=200, n_jobs=-1, random_state=42)
        return Pipeline([("vec", vec), ("scaler", scaler), ("clf", clf)])

    # numeric
    scaler = StandardScaler()
    if alg in ("auto", "random_forest"):
        clf = RandomForestClassifier(n_estimators=200, n_jobs=-1, random_state=42)
    elif alg == "logistic_regression":
        clf = LogisticRegression(max_iter=1000)
    elif alg == "svc":
        clf = SVC(kernel="rbf", probability=True, C=1.0)
    elif alg == "gradient_boosting":
        clf = GradientBoostingClassifier(n_estimators=100, random_state=42)
    else:
        clf = RandomForestClassifier(n_estimators=200, n_jobs=-1, random_state=42)
    return Pipeline([("scaler", scaler), ("clf", clf)])


def _build_regression_pipeline(feature_type: str, algorithm: str):
    """Return an unfitted sklearn Pipeline for regression."""
    _require_sklearn()
    from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
    from sklearn.linear_model import Ridge, LinearRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.feature_extraction import DictVectorizer

    alg = algorithm.lower()

    if feature_type == "text":
        vectorizer = TfidfVectorizer(max_features=20_000, sublinear_tf=True)
        if alg in ("auto", "random_forest"):
            reg = RandomForestRegressor(n_estimators=200, n_jobs=-1, random_state=42)
        elif alg in ("ridge", "linear_regression"):
            reg = Ridge(alpha=1.0)
        elif alg == "gradient_boosting":
            reg = GradientBoostingRegressor(n_estimators=100, random_state=42)
        else:
            reg = RandomForestRegressor(n_estimators=200, n_jobs=-1, random_state=42)
        return Pipeline([("tfidf", vectorizer), ("reg", reg)])

    if feature_type == "mixed-dict":
        vec = DictVectorizer(sparse=False)
        scaler = StandardScaler()
        if alg in ("auto", "random_forest"):
            reg = RandomForestRegressor(n_estimators=200, n_jobs=-1, random_state=42)
        elif alg in ("ridge", "linear_regression"):
            reg = Ridge(alpha=1.0)
        elif alg == "gradient_boosting":
            reg = GradientBoostingRegressor(n_estimators=100, random_state=42)
        else:
            reg = RandomForestRegressor(n_estimators=200, n_jobs=-1, random_state=42)
        return Pipeline([("vec", vec), ("scaler", scaler), ("reg", reg)])

    # numeric
    scaler = StandardScaler()
    if alg in ("auto", "random_forest"):
        reg = RandomForestRegressor(n_estimators=200, n_jobs=-1, random_state=42)
    elif alg in ("ridge", "linear_regression"):
        reg = Ridge(alpha=1.0)
    elif alg == "gradient_boosting":
        reg = GradientBoostingRegressor(n_estimators=100, random_state=42)
    else:
        reg = RandomForestRegressor(n_estimators=200, n_jobs=-1, random_state=42)
    return Pipeline([("scaler", scaler), ("reg", reg)])


def _build_clustering_pipeline(feature_type: str, algorithm: str, n_clusters: int):
    """Return an unfitted sklearn Pipeline for clustering."""
    _require_sklearn()
    from sklearn.cluster import KMeans, DBSCAN
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.decomposition import TruncatedSVD

    alg = algorithm.lower()

    if feature_type == "text":
        vectorizer = TfidfVectorizer(max_features=5_000, sublinear_tf=True)
        svd = TruncatedSVD(n_components=min(50, n_clusters * 5))
        if alg in ("auto", "kmeans"):
            clust = KMeans(n_clusters=n_clusters, random_state=42, n_init="auto")
        else:
            clust = DBSCAN(eps=0.5, min_samples=5)
        return Pipeline([("tfidf", vectorizer), ("svd", svd), ("clust", clust)])

    if feature_type == "mixed-dict":
        vec = DictVectorizer(sparse=False)
        scaler = StandardScaler()
        if alg in ("auto", "kmeans"):
            clust = KMeans(n_clusters=n_clusters, random_state=42, n_init="auto")
        else:
            clust = DBSCAN(eps=0.5, min_samples=5)
        return Pipeline([("vec", vec), ("scaler", scaler), ("clust", clust)])

    # numeric
    scaler = StandardScaler()
    if alg in ("auto", "kmeans"):
        clust = KMeans(n_clusters=n_clusters, random_state=42, n_init="auto")
    else:
        clust = DBSCAN(eps=0.5, min_samples=5)
    return Pipeline([("scaler", scaler), ("clust", clust)])


def _compute_classification_metrics(pipeline, X_test, y_test) -> dict:
    _require_sklearn()
    from sklearn.metrics import accuracy_score, f1_score, classification_report
    import numpy as np

    y_pred = pipeline.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred, average="weighted", zero_division=0)
    return {
        "accuracy": round(float(acc), 4),
        "f1_weighted": round(float(f1), 4),
        "test_samples": len(y_test),
    }


def _compute_regression_metrics(pipeline, X_test, y_test) -> dict:
    _require_sklearn()
    from sklearn.metrics import mean_squared_error, r2_score
    import numpy as np

    y_pred = pipeline.predict(X_test)
    r2 = r2_score(y_test, y_pred)
    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
    return {
        "r2": round(float(r2), 4),
        "rmse": round(rmse, 4),
        "test_samples": len(y_test),
    }


# ---------------------------------------------------------------------------
# Model metadata record
# ---------------------------------------------------------------------------

class ModelRecord:
    """Metadata for one trained model (stored alongside the .pkl)."""

    __slots__ = (
        "name", "task", "algorithm", "feature_type",
        "train_samples", "metrics", "trained_at",
        "label_classes",
    )

    def __init__(
        self,
        name: str,
        task: str,
        algorithm: str,
        feature_type: str,
        train_samples: int,
        metrics: dict,
        label_classes: list | None = None,
    ) -> None:
        self.name          = name
        self.task          = task
        self.algorithm     = algorithm
        self.feature_type  = feature_type
        self.train_samples = train_samples
        self.metrics       = metrics
        self.trained_at    = time.time()
        self.label_classes = label_classes or []

    def to_dict(self) -> dict:
        return {
            "name":          self.name,
            "task":          self.task,
            "algorithm":     self.algorithm,
            "feature_type":  self.feature_type,
            "train_samples": self.train_samples,
            "metrics":       self.metrics,
            "trained_at":    self.trained_at,
            "label_classes": self.label_classes,
        }


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class MLEngine:
    """
    Scikit-learn backed ML prediction engine with full persistence pipeline.

    Parameters
    ----------
    models_dir : Directory where .pkl model files are stored.
    """

    def __init__(self, models_dir: Path | str | None = None) -> None:
        self._dir  = Path(models_dir) if models_dir else _models_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        # In-memory cache: name → (pipeline, ModelRecord)
        self._cache: dict[str, tuple[Any, ModelRecord]] = {}

    # ------------------------------------------------------------------ #
    # Factory                                                              #
    # ------------------------------------------------------------------ #

    @classmethod
    def load_or_create(cls, models_dir: Path | str | None = None) -> "MLEngine":
        """
        Create an MLEngine instance.  Existing .pkl files in *models_dir*
        are lazily loaded on first predict() call — no upfront loading cost.
        """
        return cls(models_dir=models_dir)

    # ------------------------------------------------------------------ #
    # Training                                                             #
    # ------------------------------------------------------------------ #

    def train(
        self,
        name: str,
        features: list,
        labels: list | None = None,
        task: str = "classification",
        algorithm: str = "auto",
        test_size: float = 0.2,
        n_clusters: int = 5,
        auto_save: bool = True,
    ) -> dict[str, Any]:
        """
        Train and optionally persist a model.

        Parameters
        ----------
        name       : Unique model identifier (used for save/predict).
        features   : list[str] for text, list[list[float]] for numeric,
                     list[dict] for mixed.
        labels     : list of target values (not needed for clustering).
        task       : "classification" | "regression" | "clustering"
        algorithm  : "auto" or a specific algorithm name (see module docstring).
        test_size  : Fraction of data held out for evaluation (0–1).
        n_clusters : Number of clusters for KMeans clustering.
        auto_save  : If True, automatically persist the model after training.

        Returns a dict with training metrics and model metadata.
        """
        _require_sklearn()
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import LabelEncoder

        if not name or not name.strip():
            raise ValueError("Model name must be a non-empty string.")
        name = name.strip()

        if not features:
            raise ValueError("features list is empty.")

        task = task.lower()
        if task not in ("classification", "regression", "clustering"):
            raise ValueError(f"Unknown task '{task}'. Use: classification, regression, clustering.")

        feature_type = _detect_feature_type(features)
        logger.info(
            "MLEngine.train: name='%s' task=%s algo=%s features=%s n=%d",
            name, task, algorithm, feature_type, len(features),
        )

        label_encoder: LabelEncoder | None = None
        label_classes: list = []

        if task == "clustering":
            pipeline = _build_clustering_pipeline(feature_type, algorithm, n_clusters)
            t0 = time.perf_counter()
            pipeline.fit(features)
            elapsed = time.perf_counter() - t0
            cluster_labels = pipeline.named_steps.get("clust") or list(pipeline.steps)[-1][1]
            try:
                labels_out = cluster_labels.labels_.tolist()
            except AttributeError:
                labels_out = pipeline.predict(features).tolist()
            metrics = {
                "n_clusters": n_clusters,
                "train_samples": len(features),
                "elapsed_s": round(elapsed, 3),
            }
            record = ModelRecord(
                name=name, task=task, algorithm=algorithm,
                feature_type=feature_type, train_samples=len(features),
                metrics=metrics,
            )
            self._cache[name] = (pipeline, record)
            if auto_save:
                self.save(name)
            return record.to_dict()

        # Supervised: classification or regression
        if labels is None:
            raise ValueError("labels are required for classification and regression tasks.")
        if len(features) != len(labels):
            raise ValueError(
                f"Mismatch: {len(features)} features but {len(labels)} labels."
            )
        if len(features) < 4:
            raise ValueError("Need at least 4 samples for training (2 train + 2 test).")

        # Encode string labels for classification
        encoded_labels = labels
        if task == "classification":
            label_types = {type(l) for l in labels}
            if str in label_types:
                label_encoder = LabelEncoder()
                encoded_labels = label_encoder.fit_transform(labels).tolist()
                label_classes = label_encoder.classes_.tolist()
            else:
                import numpy as np
                label_classes = sorted(set(labels))

        # Train / test split
        _test_size = float(test_size)
        if len(features) < 10:
            _test_size = max(_test_size, 0.25)

        X_train, X_test, y_train, y_test = train_test_split(
            features, encoded_labels,
            test_size=_test_size,
            random_state=42,
            stratify=(encoded_labels if task == "classification" else None),
        )

        # Build and fit pipeline
        if task == "classification":
            pipeline = _build_classification_pipeline(feature_type, algorithm)
        else:
            pipeline = _build_regression_pipeline(feature_type, algorithm)

        t0 = time.perf_counter()
        pipeline.fit(X_train, y_train)
        elapsed = time.perf_counter() - t0

        # Evaluate
        if task == "classification":
            metrics = _compute_classification_metrics(pipeline, X_test, y_test)
        else:
            metrics = _compute_regression_metrics(pipeline, X_test, y_test)
        metrics["elapsed_s"] = round(elapsed, 3)
        metrics["train_samples"] = len(X_train)

        record = ModelRecord(
            name=name, task=task, algorithm=algorithm,
            feature_type=feature_type, train_samples=len(X_train),
            metrics=metrics, label_classes=label_classes,
        )
        # Store label encoder inside the record so predict() can decode
        record._label_encoder = label_encoder  # type: ignore[attr-defined]

        self._cache[name] = (pipeline, record)

        if auto_save:
            self.save(name)

        logger.info(
            "MLEngine: model '%s' trained  metrics=%s", name, metrics,
        )
        return record.to_dict()

    # ------------------------------------------------------------------ #
    # Prediction                                                           #
    # ------------------------------------------------------------------ #

    def predict(self, name: str, features: list) -> list:
        """
        Run inference on *features* using the named model.

        The model is auto-loaded from disk if not already in memory.

        Returns a list of predictions (one per sample).
        """
        pipeline, record = self._get_model(name)
        raw = pipeline.predict(features)
        # Decode label encoder if classification with string labels
        encoder = getattr(record, "_label_encoder", None)
        if encoder is not None:
            return encoder.inverse_transform(raw).tolist()
        return raw.tolist()

    def predict_proba(self, name: str, features: list) -> list[dict]:
        """
        Return class probabilities for each sample.

        Only valid for classification models with probability support.
        Returns a list of dicts: {"class_label": probability, ...}
        """
        pipeline, record = self._get_model(name)
        if record.task != "classification":
            raise ValueError(f"predict_proba is only valid for classification models (got '{record.task}').")

        try:
            probs = pipeline.predict_proba(features)
        except AttributeError:
            raise RuntimeError(
                f"Model '{name}' does not support probability predictions. "
                "Use predict() instead, or choose 'random_forest', 'logistic_regression', or 'svc'."
            )

        classes = record.label_classes
        encoder = getattr(record, "_label_encoder", None)
        if encoder is not None:
            classes = encoder.classes_.tolist()

        result = []
        for row in probs:
            result.append({
                str(cls): round(float(p), 4)
                for cls, p in zip(classes, row)
            })
        return result

    # ------------------------------------------------------------------ #
    # Persistence                                                          #
    # ------------------------------------------------------------------ #

    def save(self, name: str) -> Path:
        """
        Persist the named model to disk as a .pkl checkpoint using joblib.

        Returns the path written to.
        """
        if name not in self._cache:
            raise KeyError(f"No in-memory model named '{name}'. Train it first.")

        joblib = _joblib()
        pipeline, record = self._cache[name]

        pkl_path = self._dir / f"{name}.pkl"
        meta_path = self._dir / f"{name}.meta.json"

        payload = {
            "pipeline": pipeline,
            "record": record,
        }
        joblib.dump(payload, pkl_path, compress=3)

        # Write human-readable metadata sidecar
        meta = record.to_dict()
        meta["pkl_path"] = str(pkl_path)
        meta_path.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")

        logger.info("MLEngine: model '%s' saved to '%s'.", name, pkl_path)
        return pkl_path

    def load(self, name: str) -> "MLEngine":
        """
        Load a model from disk into the in-memory cache.

        Raises FileNotFoundError if the .pkl does not exist.
        Returns self for method chaining.
        """
        joblib = _joblib()
        pkl_path = self._dir / f"{name}.pkl"
        if not pkl_path.exists():
            raise FileNotFoundError(
                f"No saved model '{name}' at '{pkl_path}'. Train it first."
            )

        payload = joblib.load(pkl_path)
        pipeline = payload["pipeline"]
        record   = payload["record"]
        self._cache[name] = (pipeline, record)

        logger.info("MLEngine: model '%s' loaded from '%s'.", name, pkl_path)
        return self

    def delete_model(self, name: str) -> bool:
        """
        Remove a model from memory and delete its .pkl and .meta.json from disk.

        Returns True if deleted, False if not found.
        """
        found = False
        if name in self._cache:
            del self._cache[name]
            found = True

        pkl_path  = self._dir / f"{name}.pkl"
        meta_path = self._dir / f"{name}.meta.json"
        for p in (pkl_path, meta_path):
            if p.exists():
                p.unlink()
                found = True

        if found:
            logger.info("MLEngine: model '%s' deleted.", name)
        return found

    # ------------------------------------------------------------------ #
    # Querying                                                             #
    # ------------------------------------------------------------------ #

    def list_models(self) -> list[dict]:
        """
        Return metadata for all models — loaded (in-memory) and saved (on disk).
        Disk models are listed from their .meta.json sidecars without loading the .pkl.
        """
        result: dict[str, dict] = {}

        # Discover on-disk models via .meta.json sidecars (cheap, no pkl load)
        for meta_path in sorted(self._dir.glob("*.meta.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                n = meta.get("name", meta_path.stem.replace(".meta", ""))
                meta["loaded"] = n in self._cache
                result[n] = meta
            except Exception:
                pass  # skip corrupt metadata files

        # Overlay in-memory models (may have been trained but not yet saved)
        for name, (_, record) in self._cache.items():
            d = record.to_dict()
            d["loaded"] = True
            result[name] = d

        return list(result.values())

    def get_model_info(self, name: str) -> dict | None:
        """Return metadata dict for a named model, or None if not found."""
        # Check cache first
        if name in self._cache:
            _, record = self._cache[name]
            d = record.to_dict()
            d["loaded"] = True
            return d
        # Check disk
        meta_path = self._dir / f"{name}.meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                meta["loaded"] = False
                return meta
            except Exception:
                pass
        return None

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    def _get_model(self, name: str) -> tuple[Any, "ModelRecord"]:
        """Return (pipeline, record) — auto-loads from disk if needed."""
        if name not in self._cache:
            try:
                self.load(name)
            except FileNotFoundError:
                raise KeyError(
                    f"Model '{name}' not found. "
                    "Train it with MLEngine.train() or load it with MLEngine.load()."
                )
        return self._cache[name]
