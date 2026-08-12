from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from atlas.features.definitions import FEATURE_NAMES
from atlas.historical import (
    HistoricalDatasetBuilder,
    HistoricalDatasetRow,
    MatchCatalogue,
    TeamCatalogue,
)
from atlas.registry import ModelFamily, ModelStage
from atlas.registry.models import LabelSource
from atlas.training import TrainingPipeline


def test_match_catalogue_deduplicates_cross_provider_match() -> None:
    teams = TeamCatalogue()
    matches = MatchCatalogue()
    observed = datetime(2024, 6, 1, tzinfo=timezone.utc)
    home = teams.resolve(
        provider="api_football",
        external_id="10",
        name="Brazil",
        country_code="BR",
        observed_at=observed,
    )
    away = teams.resolve(
        provider="api_football",
        external_id="20",
        name="Argentina",
        country_code="AR",
        observed_at=observed,
    )
    competition_id = uuid4()
    kickoff = datetime(2024, 6, 2, 21, 0, tzinfo=timezone.utc)
    first = matches.resolve(
        provider="api_football",
        external_id="12345",
        competition_id=competition_id,
        home_team_id=home,
        away_team_id=away,
        kickoff_at=kickoff,
        observed_at=observed,
    )
    second = matches.resolve(
        provider="football_data",
        external_id="ABC-998",
        competition_id=competition_id,
        home_team_id=home,
        away_team_id=away,
        kickoff_at=kickoff,
        observed_at=observed,
    )
    assert first == second
    assert len(matches.mappings) == 2


def _row(year: int, provider: str = "api_football") -> HistoricalDatasetRow:
    return HistoricalDatasetRow(
        match_id=uuid4(),
        competition_id=uuid4(),
        event_ts=datetime(year, 6, 1, tzinfo=timezone.utc),
        features={name: 0.5 for name in FEATURE_NAMES},
        provider=provider,
        label="balanced",
        relevance=1,
    )


def test_historical_dataset_temporal_split_and_metadata() -> None:
    dataset = HistoricalDatasetBuilder(
        feature_schema_version=2,
        train_until_year=2022,
        validation_year=2023,
        test_year=2024,
    ).build([_row(2021), _row(2022), _row(2023), _row(2024, "football_data")])

    assert dataset.version.startswith("hist-")
    assert dataset.train.X.shape == (2, len(FEATURE_NAMES))
    assert dataset.validation.X.shape == (1, len(FEATURE_NAMES))
    assert dataset.test.X.shape == (1, len(FEATURE_NAMES))
    assert dataset.metadata["label_source"] == LabelSource.historical_outcome.value
    assert dataset.provider_composition == {"api_football": 3, "football_data": 1}


async def test_historical_training_stages_without_promotion(
    training_pipeline: TrainingPipeline,
) -> None:
    rows = [_row(2020), _row(2021), _row(2022), _row(2023), _row(2024)]
    dataset = HistoricalDatasetBuilder(
        feature_schema_version=1,
        train_until_year=2022,
        validation_year=2023,
        test_year=2024,
    ).build(rows)
    result = await training_pipeline.train_historical(ModelFamily.similarity, dataset)

    assert result.succeeded
    assert result.version is not None
    assert result.version.stage == ModelStage.staged
    assert result.version.dataset_version == dataset.version
    assert result.version.dataset_metadata["sample_count"] == 5
