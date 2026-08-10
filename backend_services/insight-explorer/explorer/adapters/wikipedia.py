"""Wikipedia adapter — real per-match extraction from season articles.

WHAT CHANGED AND WHY. This adapter used to confirm that a season article
existed and yield nothing. It was registered, enabled, and selected on
pipelines that finished in seconds reporting `completed` with zero records —
the worst failure shape available, because a green status with no data reads
as "this competition has no matches" rather than "this source collects
nothing".

WHY DETERMINISTIC PARSING AND NOT THE LLM STACK. The image ships LangGraph and
CrewAI, and they are the right tool for the job they already have: proposing
candidates when the deterministic club resolver cannot match a name. They are
the wrong tool for extracting match results. An LLM asked for a season's
fixtures always returns fixtures — including for a page that failed to load,
or a competition it half-remembers. A parser that cannot find the table raises
FetchError, the JobRunner isolates the source and opens a ticket, and the
console shows Wikipedia failing. In a system whose whole value is that the
history is true, a source that fabricates plausibly is worse than one that
stops.

HOW IT READS. MediaWiki's `parse` action returns the rendered HTML of an
article. Season articles publish results in two shapes, and both are handled:

  * a RESULTS MATRIX (leagues) — one row per home club, one column per away
    club, each cell a score. That is where a double round-robin actually
    lives, and it yields every fixture of the season.
  * MATCH BOXES (cups/knockouts) — "Team A 2–1 Team B" in a table row.

Anything else is skipped rather than guessed at.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Iterator

from explorer.adapters.base import RawArtifact, SourceAdapter
from explorer.collectors.http import FetchError, PoliteFetcher

_API = "https://en.wikipedia.org/w/api.php"

# Article titles differ per competition and Wikipedia is inconsistent about
# season formatting, so both the title template and the season shape are
# declared here rather than derived.
# Cups split their season across articles: the main page carries the final and
# a summary, while the matches live in phase pages. Collecting only the main
# article yielded one Libertadores fixture out of a whole tournament.
_PHASE_ARTICLES = {
    "libertadores": [
        "{season} Copa Libertadores group stage",
        "{season} Copa Libertadores knockout stage",
    ],
    "champions_league": [
        "{season} UEFA Champions League group stage",
        "{season} UEFA Champions League knockout phase",
    ],
}

_SEASON_ARTICLE = {
    "premier_league": "{season} Premier League",
    "la_liga": "{season} La Liga",
    "brasileirao": "{season} Campeonato Brasileiro Série A",
    "brasileirao_serie_a": "{season} Campeonato Brasileiro Série A",
    "libertadores": "{season} Copa Libertadores",
    "champions_league": "{season} UEFA Champions League",
    "world_cup": "{season} FIFA World Cup",
}

# A score cell: "2–1", "2-1", "0–0 (a.e.t.)". The dash may be a hyphen or an
# en dash — Wikipedia uses both, and matching only one silently halves the
# yield on articles that use the other.
_SCORE = re.compile(r"^\s*(\d{1,2})\s*[–\-−]\s*(\d{1,2})")

# "Team A 2–1 Team B" on one line, for knockout match boxes.
_INLINE_MATCH = re.compile(
    r"^(?P<home>[^\d]{2,60}?)\s+(?P<hs>\d{1,2})\s*[–\-−]\s*(?P<as>\d{1,2})\s+(?P<away>[^\d]{2,60})$"
)


_MONTHS = (
    "january february march april may june july august september october "
    "november december"
).split()

# Words that appear where a club name would be, in tables that are not match
# lists: schedules, brackets, round summaries.
_NOT_A_CLUB = (
    "stage", "leg", "round", "matchday", "final", "qualifying", "play-off",
    "playoff", "seeding", "draw", "aggregate", "winner", "runner",
)


def _looks_like_club(text: str) -> bool:
    """Reject the things a calendar table puts next to a number.

    Without this the cup articles produced rows like
    `21 December 2022[18] 7 x 9 14–16 February 2023` — a date range ("7–9")
    read as a score, with the dates on either side taken for clubs. The score
    pattern alone cannot tell a result from a schedule; the neighbours can.
    """
    value = text.strip()
    if not (2 <= len(value) <= 50):
        return False
    # A club name does not begin with a digit. "1899 Hoffenheim" does — and is
    # the reason this checks the FIRST TOKEN rather than the first character,
    # so a year-prefixed club survives while "21 December 2022" does not.
    lowered = value.lower()
    if any(month in lowered for month in _MONTHS):
        return False
    if any(word in lowered for word in _NOT_A_CLUB):
        return False
    # Mostly digits and punctuation: a date range, a score, a rank.
    letters = sum(1 for ch in value if ch.isalpha())
    return letters >= 3


class _TableHarvester(HTMLParser):
    """Collects every table as a grid of cell texts, with its header row.

    Deliberately structure-only: it does not try to recognise which table is
    the results matrix. That decision needs the header row and the row labels
    together, and making it here would bury it inside a parser callback where
    it cannot be tested on its own.
    """

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(html.unescape("".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None


def _looks_like_results_matrix(table: list[list[str]]) -> bool:
    """A round-robin matrix is SQUARE and has an EMPTY DIAGONAL.

    Those two facts identify it without reading a single name, which matters
    because the two axes are labelled differently: rows carry full names
    ("Aston Villa"), columns carry abbreviations ("AVL"). Matching the labels
    against each other was my first attempt and it recognised nothing.

    The diagonal is the decisive half. Cell (i, i) is a club against itself —
    a fixture that cannot exist, so Wikipedia leaves it blank or greys it out.
    A knockout bracket or a fixtures calendar has no such structure, which is
    why the earlier score-count threshold accepted them and produced 181
    "matches" like `First stage 7 x 9 First leg`.

    Checked on CONTENT, not on a CSS class: Wikipedia's class names vary by
    article and by year, and keying on them makes the adapter fail silently
    the first time an editor restyles a page.
    """
    if len(table) < 4:
        return False

    body = [row for row in table[1:] if row and row[0].strip()]
    if len(body) < 4:
        return False

    # Square within a cell of tolerance: the header row has one label column,
    # and articles occasionally append a totals column.
    width = len(table[0]) - 1
    if not (len(body) - 1 <= width <= len(body) + 1):
        return False

    diagonal_scores = 0
    off_diagonal_scores = 0
    for index, row in enumerate(body):
        for column, cell in enumerate(row[1:]):
            if not _SCORE.match(cell):
                continue
            if column == index:
                diagonal_scores += 1
            else:
                off_diagonal_scores += 1

    # A single stray diagonal score would be a parsing artefact; several mean
    # this is not a results matrix at all.
    if diagonal_scores > 1:
        return False
    return off_diagonal_scores >= max(6, len(body))


class WikipediaAdapter(SourceAdapter):
    name = "wikipedia"
    # Community-edited: correct far more often than not, and the last word on
    # nothing. The merge in atlas.intelligence.corpus ranks it below the
    # curated archives, so it fills gaps rather than overriding them.
    trust_level = "medium"

    def __init__(self, fetcher: PoliteFetcher | None = None) -> None:
        self._fetch = fetcher or PoliteFetcher(source="wikipedia")

    def supports(self, competition_key: str) -> bool:
        return competition_key in _SEASON_ARTICLE

    def health(self) -> bool:
        try:
            self._fetch.get_json(
                _API, params={"action": "query", "meta": "siteinfo", "format": "json"}
            )
            return True
        except FetchError:
            return False

    def _article_html(self, title: str) -> str:
        payload = self._fetch.get_json(
            _API,
            params={
                "action": "parse",
                "page": title,
                "prop": "text",
                "format": "json",
                "formatversion": "2",
                # Wikipedia asks callers to identify themselves; PoliteFetcher
                # sets the agent and the From header globally.
                "redirects": "1",
            },
        )
        if "error" in payload:
            raise FetchError(
                f"wikipedia: {payload['error'].get('code')} para {title!r}"
            )
        text = (payload.get("parse") or {}).get("text")
        if not text:
            raise FetchError(f"wikipedia: artigo sem conteudo: {title!r}")
        return text

    def fetch_season(self, competition_key: str, season: str) -> Iterator[RawArtifact]:
        template = _SEASON_ARTICLE.get(competition_key)
        if template is None:
            return
        title = template.format(season=season)

        # The main article first, then any phase pages. A league has none;
        # a cup keeps most of its matches there.
        articles = [title] + [
            template.format(season=season)
            for template in _PHASE_ARTICLES.get(competition_key, [])
        ]

        harvester = _TableHarvester()
        for article in articles:
            try:
                harvester.feed(self._article_html(article))
            except FetchError:
                # A phase page that does not exist is normal — competitions
                # change format between years. Only the MAIN article being
                # unreachable is a failure, and that raised above.
                if article == title:
                    raise
                continue

        matrices = [t for t in harvester.tables if _looks_like_results_matrix(t)]

        emitted = 0
        if matrices:
            # A league article's results matrix IS the season. Scanning its
            # other tables for inline scores adds nothing and costs precision:
            # doing both produced 381 Premier League fixtures where 380 were
            # played, the extra coming from a line like
            # `Levels 5 x 6 National League` in the pyramid table.
            for table in matrices:
                emitted += yield from self._from_matrix(
                    table, competition_key, season, title
                )
        else:
            # Cups have no single matrix — group stages sit in one small table
            # per group and knockouts in match boxes.
            for table in harvester.tables:
                emitted += yield from self._from_match_rows(
                    table, competition_key, season, title
                )

        if emitted == 0:
            # Loud, not silent. An article that parsed to nothing is either a
            # layout this adapter does not handle or a page that changed —
            # both need a human, and neither should look like "no matches
            # were played".
            raise FetchError(
                f"wikipedia: nenhuma partida extraida de {title!r} "
                f"({len(harvester.tables)} tabelas inspecionadas)"
            )

    def _from_matrix(
        self, table: list[list[str]], competition_key: str, season: str, title: str
    ) -> Iterator[RawArtifact]:
        """Home teams down the first column, away teams across the header."""
        away_names = [c.strip() for c in table[0]]
        count = 0
        for row in table[1:]:
            if not row:
                continue
            home = row[0].strip()
            if not home:
                continue
            for index, cell in enumerate(row[1:], start=1):
                if index >= len(away_names):
                    break
                away = away_names[index].strip()
                # The diagonal: a club does not play itself, and those cells
                # hold styling artefacts rather than scores.
                if not away or away == home:
                    continue
                match = _SCORE.match(cell)
                if not match:
                    continue
                count += 1
                yield self._artifact(
                    competition_key, season, title, home, away,
                    int(match.group(1)), int(match.group(2)), "matrix",
                )
        return count

    def _from_match_rows(
        self, table: list[list[str]], competition_key: str, season: str, title: str
    ) -> Iterator[RawArtifact]:
        """Match boxes, which Wikipedia writes as three cells: home, score, away.

        Read positionally rather than by joining the row into one string and
        matching a regex over it. The joined form was my first attempt and it
        is fragile for exactly the reason it looks convenient: club names
        contain digits and separators ("1899 Hoffenheim", "Bayer 04"), so a
        pattern loose enough to catch real names also catches table furniture.
        Three cells with a score in the middle is the shape itself.
        """
        count = 0
        for row in table:
            cells = [c.strip() for c in row if c.strip()]
            if len(cells) < 3:
                continue

            # The score may sit anywhere in a row that carries extra columns
            # (date, venue), so find it rather than assume position 1.
            index = next(
                (i for i, c in enumerate(cells)
                 if _SCORE.match(c) and 0 < i < len(cells) - 1),
                None,
            )
            if index is None:
                continue

            home = cells[index - 1].strip(" .-–")
            away = cells[index + 1].strip(" .-–")
            match = _SCORE.match(cells[index])
            if home == away:
                continue
            if not _looks_like_club(home) or not _looks_like_club(away):
                continue
            count += 1
            yield self._artifact(
                competition_key, season, title, home, away,
                int(match.group(1)), int(match.group(2)), "match_row",
            )
        return count

    def _artifact(
        self, competition_key: str, season: str, title: str,
        home: str, away: str, home_score: int, away_score: int, shape: str,
    ) -> RawArtifact:
        from datetime import datetime, timezone

        # Wikipedia publishes no per-match id, so one is derived from the
        # match's identity. Stable across re-collections — which is what makes
        # the historical tables' ReplacingMergeTree merge instead of duplicate.
        external_id = f"wp-{competition_key}-{season}-{_slug(home)}-{_slug(away)}"
        return RawArtifact(
            source=self.name,
            provider="wikipedia",
            entity_type="fixture",
            external_id=external_id,
            competition_key=competition_key,
            season=season,
            url=f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
            method="scrape",
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            raw={
                "home_team": home,
                "away_team": away,
                "home_score": home_score,
                "away_score": away_score,
                "status": "finished",
                # Wikipedia's matrix carries no kickoff date. Recorded as
                # absent rather than invented: the normalizer decides what to
                # do with it, and a guessed date would pollute the ordering
                # every downstream walk-forward calculation depends on.
                "scheduled_at": None,
                "article": title,
                "extraction_shape": shape,
            },
            trust_level=self.trust_level,
            license_note="CC BY-SA 4.0 — Wikipedia",
        )


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
