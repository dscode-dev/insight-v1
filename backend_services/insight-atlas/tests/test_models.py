from __future__ import annotations

from uuid import uuid4

import numpy as np

from atlas.features.definitions import FEATURE_NAMES
from atlas.models import (
    AnomalyModel,
    ContextualClassifierModel,
    ClusterModel,
    DensityClusterModel,
    ContextualRankerModel,
    SimilarityIndex,
)
from atlas.models.classifier import CONTEXT_LABELS, bootstrap_labels
from atlas.models.ranker import bootstrap_relevance


def test_anomaly_scores_in_range(training_matrix: np.ndarray) -> None:
    model = AnomalyModel.train(training_matrix)
    sample = training_matrix[0].tolist()
    result = model.score_vector(sample)
    assert 0.0 <= result.score <= 1.0
    assert isinstance(result.is_anomaly, bool)
    assert len(result.top_factors) >= 1
    for f, c in result.top_factors:
        assert f in FEATURE_NAMES
        assert c >= 0.0


def test_anomaly_explainability_z_scores(training_matrix: np.ndarray) -> None:
    """An obvious outlier (large positive shift on one feature) must
    surface that feature as the top contributing factor."""
    model = AnomalyModel.train(training_matrix)
    sample = training_matrix.mean(axis=0).tolist()
    idx = FEATURE_NAMES.index("market_volatility")
    sample[idx] = 10.0  # well outside the training envelope
    result = model.score_vector(sample, top_k=3)
    assert result.top_factors[0][0] == "market_volatility"


def test_cluster_assigns_known_id(training_matrix: np.ndarray) -> None:
    model = ClusterModel.train(training_matrix, n_clusters=3)
    sample = training_matrix[10].tolist()
    a = model.assign(sample)
    assert 0 <= a.cluster_id < 3
    assert a.distance >= 0.0
    assert len(a.top_factors) >= 1


def test_density_cluster_assigns_or_marks_noise(training_matrix: np.ndarray) -> None:
    model = DensityClusterModel.train(training_matrix, min_cluster_size=10)
    a = model.assign(training_matrix[0].tolist())
    # Either a real cluster (with id >= 0) or noise.
    assert isinstance(a.is_noise, bool)
    assert a.cluster_id == -1 if a.is_noise else a.cluster_id >= 0


def test_classifier_bootstrap_labels_are_categorical(training_matrix: np.ndarray) -> None:
    y = bootstrap_labels(training_matrix)
    assert y.shape == (training_matrix.shape[0],)
    assert set(int(v) for v in y).issubset(set(range(len(CONTEXT_LABELS))))


def test_classifier_trains_and_predicts(training_matrix: np.ndarray) -> None:
    y = bootstrap_labels(training_matrix)
    model = ContextualClassifierModel.train(training_matrix, y)
    pred = model.predict(training_matrix[0].tolist())
    assert pred.label in CONTEXT_LABELS
    assert 0.0 <= pred.confidence <= 1.0
    # Local explanation: at least one factor is non-zero.
    assert any(c > 0.0 for _, c in pred.top_factors)


def test_ranker_trains_and_scores(training_matrix: np.ndarray) -> None:
    y = bootstrap_relevance(training_matrix)
    model = ContextualRankerModel.train(training_matrix, y)
    s = model.score_vector(training_matrix[0].tolist())
    assert isinstance(s.score, float)
    # Importance distribution should be non-degenerate.
    assert sum(model.feature_importance.values()) > 0


def test_similarity_index_finds_self_first() -> None:
    rng = np.random.default_rng(0)
    n = 20
    matrix = rng.normal(0.5, 0.1, size=(n, len(FEATURE_NAMES)))
    ids = [uuid4() for _ in range(n)]
    idx = SimilarityIndex.build(list(zip(ids, matrix.tolist())))
    query = matrix[3].tolist()
    out = idx.topk(query, k=3)
    assert out[0].match_id == ids[3]
    assert out[0].similarity >= out[1].similarity
