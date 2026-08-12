"""The ruler has to be right, or every later decision inherits its error.

These fix the two judgements that are easy to get subtly wrong and that
nothing downstream would catch: what counts as a CONSTANT dimension, and
what counts as a match.
"""

from __future__ import annotations

import json
import math

from atlas.diagnostics.coverage import measure_coverage
from atlas.diagnostics.module_map import map_tables
from atlas.diagnostics.vector_report import (
    measure_dimensions,
    measure_retrieval,
    measure_similarity,
    standardise,
)
from atlas.vector_memory.embedding import layout_v1, layout_v2


def _normalise(values):
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values] if norm else list(values)


class TestLayout:
    def test_v2_names_every_position(self):
        names = layout_v2()
        assert len(names) == 37
        assert "?" not in names
        assert names[36] == "bias"

    def test_v1_names_every_position(self):
        names = layout_v1()
        assert len(names) == 32
        assert "?" not in names

    def test_regime_collision_is_visible(self):
        """Three regimes share slot 3. The name shows all of them rather
        than letting the last one silently win — a diagnostic that hides
        a collision is how the collision survives."""
        assert "+" in layout_v2()[3]


class TestDimensions:
    def test_constant_is_judged_against_the_bias_term(self):
        """A component identical in every record BEFORE normalisation still
        varies after it, because its magnitude rides on the vector's norm.

        This is the exact case that made `line_movement` — 0.5 in all 7.261
        production rows — look like 6.490 distinct values. Reading the raw
        standard deviation calls it informative; the ratio to the bias term
        calls it constant, which is the truth.
        """
        rows = []
        for scale in (1.0, 2.0, 3.0, 4.0):
            rows.append(_normalise([scale, 0.5, 1.0]))

        stats = measure_dimensions(rows, ("varia", "fixa", "bias"), bias_index=2)
        assert stats[0].constant is False
        assert stats[1].constant is True
        assert stats[1].fixed_value == 0.5
        # It absolutely does vary after normalisation — that is the trap.
        assert stats[1].stdev > 0
        assert stats[1].distinct > 1

    def test_identical_columns_are_reported_once(self):
        """Both copies must VARY, or they are constants and the other rule
        applies. This is `beh:volatile` and `trend:volatility_trend` in
        production: one bit written into two slots."""
        rows = [_normalise([a, a * 0.5, a * 0.5, 1.0]) for a in (1.0, 2.0, 3.0)]
        stats = measure_dimensions(rows, ("a", "b", "c", "bias"), bias_index=3)
        assert not stats[1].constant and not stats[2].constant
        assert stats[1].duplicate_of is None
        assert stats[2].duplicate_of == 1

    def test_a_constant_column_is_not_also_called_a_duplicate(self):
        """Two dead columns duplicating each other is not news — both are
        already reported as carrying nothing, and counting them twice would
        overstate how much the layout could shrink."""
        rows = [_normalise([a, 0.0, 0.0, 1.0]) for a in (1.0, 2.0, 3.0)]
        stats = measure_dimensions(rows, ("a", "b", "c", "bias"), bias_index=3)
        assert stats[1].constant and stats[2].constant
        assert stats[2].duplicate_of is None


class TestSimilarity:
    def test_random_pairs_of_identical_vectors_sit_at_one(self):
        rows = [_normalise([1.0, 1.0, 1.0])] * 50
        stat = measure_similarity(rows, label="iguais", pairs=200)
        assert stat.median > 0.999

    def test_standardising_pulls_random_pairs_toward_zero(self):
        """The production finding, as a test: components confined to [0, 1]
        put every vector in one orthant, so nothing can be far from
        anything. Centring is what gives the score somewhere to move.
        """
        rows = [
            _normalise([0.5 + 0.1 * (i % 5), 0.4 + 0.1 * (i % 3), 0.6, 1.0])
            for i in range(120)
        ]
        antes = measure_similarity(rows, label="antes", pairs=4000)
        depois = measure_similarity(
            standardise(rows, [0, 1]), label="depois", pairs=4000
        )
        assert antes.median > 0.9
        assert abs(depois.median) < abs(antes.median)
        assert depois.stdev > antes.stdev


class TestRetrieval:
    def test_reports_lift_against_the_base_rate(self):
        """The floor is the corpus's own most common outcome, not chance.
        A neighbourhood that cannot beat 'always say home win' is describing
        nothing, however confident its scores look.
        """
        entries = []
        outcomes = {}
        for i in range(200):
            uid = f"m{i:03d}"
            # Two clean clusters, each with its own outcome: retrieval
            # should be near-perfect and the lift clearly positive.
            if i % 2:
                entries.append((f"2024-01-{i:02d}", uid, _normalise([1.0, 0.0])))
                outcomes[uid] = "HOME_WIN"
            else:
                entries.append((f"2024-01-{i:02d}", uid, _normalise([0.0, 1.0])))
                outcomes[uid] = "AWAY_WIN"

        stats = measure_retrieval(
            entries, outcomes, k_values=(5,), queries=40, warmup=100
        )
        assert stats and stats[0].agreement > 0.9
        assert stats[0].lift > 0.3

    def test_no_outcomes_means_no_reading_rather_than_a_fake_one(self):
        entries = [("2024-01-01", "m1", [1.0, 0.0])]
        assert measure_retrieval(entries, {}, warmup=0) == []


class TestCoverage:
    def _write(self, root, relative, records):
        path = root / relative
        path.mkdir(parents=True, exist_ok=True)
        with (path / "part-0001.jsonl").open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")

    def _fixture(self, home, away, day="2024-03-01"):
        return {
            "competition": {"competition_key": "premier_league"},
            "season": "2023-2024",
            "payload": {
                "status": "finished",
                "scheduled_at": f"{day}T15:00:00Z",
                "home_team": {"club_id": home},
                "away_team": {"club_id": away},
                "score": {"home": 1, "away": 0},
            },
        }

    def test_one_match_from_two_sources_counts_once(self, tmp_path):
        """The identity rule, which is the whole reason this is trustworthy:
        the same game reported by two sources is one match, never two."""
        validated = tmp_path / "validated"
        self._write(
            validated, "premier_league/2023-2024/football_data/fixture",
            [self._fixture("arsenal", "chelsea")],
        )
        self._write(
            validated, "premier_league/2023-2024/openfootball/fixture",
            [self._fixture("arsenal", "chelsea")],
        )
        report = measure_coverage(str(validated))
        assert report.total_matches == 1
        assert report.blocks["core"] == 1

    def test_missing_blocks_make_a_record_incomplete(self, tmp_path):
        validated = tmp_path / "validated"
        self._write(
            validated, "premier_league/2023-2024/football_data/fixture",
            [self._fixture("arsenal", "chelsea")],
        )
        report = measure_coverage(str(validated))
        assert report.blocks["market"] == 0
        assert report.complete == 0

    def test_source_native_rows_are_not_called_malformed(self, tmp_path):
        """A football-data CSV row is the most complete record in the lake.
        Reporting it as broken would point the reader away from exactly the
        data that fills the dead market dimensions."""
        raw = tmp_path / "raw"
        self._write(
            raw, "premier_league/2023-2024/football_data/fixture",
            [{
                "external_id": "fd-1", "competition_key": "premier_league",
                "season": "2023-2024",
                "raw": {"HomeTeam": "Burnley", "AwayTeam": "Man City", "B365H": "8"},
            }],
        )
        report = measure_coverage(str(tmp_path / "validated"), str(raw))
        assert report.source_native == 1
        assert report.malformed_lines == 0


class TestTableMap:
    def test_empty_table_with_code_behind_it_is_decorative(self, tmp_path):
        package = tmp_path / "atlas" / "trends"
        package.mkdir(parents=True)
        (tmp_path / "atlas" / "__init__.py").write_text("", encoding="utf-8")
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "engine.py").write_text(
            "SQL = 'INSERT INTO atlas.trend_events VALUES (1)'\n", encoding="utf-8"
        )

        uses = {u.table: u for u in map_tables(tmp_path, {
            "atlas.trend_events": 0, "atlas.esquecida": 0, "atlas.viva": 10,
        })}
        assert uses["atlas.trend_events"].decorative is True
        assert uses["atlas.trend_events"].referenced_by == ("trends",)
        # Empty and unreferenced is a leftover migration, not a feature that
        # runs and produces nothing. Different problem, different fix.
        assert uses["atlas.esquecida"].decorative is False
        assert uses["atlas.viva"].decorative is False


class TestPrecision:
    def test_a_lift_smaller_than_its_margin_is_not_conclusive(self):
        """Guards the exact confusion this package was built to end: the
        same corpus read +6.9 points on 120 queries and +5.6 on 400. The
        number without its error bars invites celebrating noise."""
        from atlas.diagnostics.vector_report import RetrievalStat

        ruidoso = RetrievalStat(
            k=25, queries=40, agreement=0.52, base_rate=0.50, top_similarity=0.9
        )
        assert ruidoso.lift > 0
        assert ruidoso.conclusive is False

        firme = RetrievalStat(
            k=25, queries=4000, agreement=0.52, base_rate=0.50, top_similarity=0.9
        )
        assert firme.conclusive is True
        assert firme.margin < ruidoso.margin


class TestSemTermoDeVies:
    def test_bias_index_None_nao_inventa_constante(self):
        """Passar 0 em vez de None fazia a dimensão 0 ser uma razão consigo
        mesma — sempre 1,0, sempre 'constante'. A régua reportou como sem
        informação uma dimensão que varia em 3.784 valores."""
        rows = [_normalise([float(i), float(i % 3), 5.0]) for i in range(1, 40)]

        com_vies = measure_dimensions(rows, ("a", "b", "c"), bias_index=0)
        assert com_vies[0].constant is True  # o falso positivo, reproduzido

        sem_vies = measure_dimensions(rows, ("a", "b", "c"), bias_index=None)
        assert sem_vies[0].constant is False
        assert sem_vies[1].constant is False

    def test_e_ainda_acha_a_constante_de_verdade(self):
        """Num espaço padronizado, feature que não varia é exatamente 0,0 em
        toda linha e continua 0,0 depois de normalizar."""
        rows = [_normalise([float(i), 0.0, 1.0]) for i in range(1, 30)]
        stats = measure_dimensions(rows, ("varia", "morta", "outra"), bias_index=None)
        assert stats[1].constant is True
        assert stats[0].constant is False
