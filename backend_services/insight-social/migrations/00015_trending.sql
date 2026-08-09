-- +goose Up
-- +goose StatementBegin
--
-- EXPLORAR-V1 — "em alta", as the platform owner defined it:
--
--     "quantidade de acesso ao post, curtidas, interações por segundos,
--      comentários"
--
-- Three of those four already have data. The first does not: nothing in this
-- schema records that a post was seen. No table, no column, no convention —
-- so the leading signal of the definition had no source at all.
--
-- WHY BUCKETS AND NOT A COUNTER. "Interações por segundo" is a RATE, and a
-- running total cannot answer it: a post with 10,000 views accumulated over a
-- month and one with 10,000 in an hour are indistinguishable once summed. The
-- rate is the whole point of "em alta" — it separates a post rising now from
-- one that was popular last week.
--
-- WHY NOT ONE ROW PER VIEW. A view happens every time a post renders; at feed
-- scale that is the highest-volume write in the system, and an append-only
-- table would outgrow the posts it describes by orders of magnitude. Bucketed
-- counters bound it: one row per post per five minutes, however many views
-- land in it.
--
-- FIVE MINUTES is short enough to see something accelerating and long enough
-- that a post viewed continuously for a day costs 288 rows, not a million.
CREATE TABLE IF NOT EXISTS post_view_buckets (
    post_id      UUID        NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    bucket_start TIMESTAMPTZ NOT NULL,
    views        BIGINT      NOT NULL DEFAULT 0,
    -- Distinct viewers, approximated by the caller: two people opening a post
    -- and one person opening it twice are different facts, and a raw view
    -- count cannot tell them apart.
    viewers      BIGINT      NOT NULL DEFAULT 0,

    PRIMARY KEY (post_id, bucket_start),
    CONSTRAINT post_view_buckets_views_check   CHECK (views >= 0),
    CONSTRAINT post_view_buckets_viewers_check CHECK (viewers >= 0)
);

-- The trending scan reads a time window across ALL posts, so the leading
-- column is the bucket, not the post.
CREATE INDEX IF NOT EXISTS ix_post_view_buckets_window
    ON post_view_buckets (bucket_start DESC, post_id);

-- Truncation lives in SQL, not in each caller. Every writer must agree on
-- where a bucket starts, or the same minute lands in two rows and the rate is
-- halved.
CREATE OR REPLACE FUNCTION post_view_bucket(at TIMESTAMPTZ)
RETURNS TIMESTAMPTZ
LANGUAGE sql IMMUTABLE AS
$$ SELECT date_bin(INTERVAL '5 minutes', at, TIMESTAMPTZ '2000-01-01') $$;

-- Record views. The UPSERT is what keeps this cheap: concurrent writers for
-- the same post and minute contend on one row instead of inserting millions.
CREATE OR REPLACE FUNCTION record_post_views(
    p_post_id UUID, p_views BIGINT, p_viewers BIGINT DEFAULT 0
) RETURNS VOID
LANGUAGE sql AS
$$
    INSERT INTO post_view_buckets (post_id, bucket_start, views, viewers)
    VALUES (p_post_id, post_view_bucket(NOW()), p_views, p_viewers)
    ON CONFLICT (post_id, bucket_start) DO UPDATE
       SET views   = post_view_buckets.views   + EXCLUDED.views,
           viewers = post_view_buckets.viewers + EXCLUDED.viewers;
$$;

-- ---------------------------------------------------------------------------
-- The score.
--
-- A FUNCTION, not a materialized view. The window is a parameter — Explorar
-- wants the last hour, a resenha might want the last day — and a materialized
-- view would fix one window and force a refresh cadence nobody chose.
--
-- WEIGHTS ARE DELIBERATE AND WRONG TO GUESS SILENTLY. A view costs nothing, a
-- like costs a tap, a comment costs a sentence, a share costs someone's
-- reputation with their own followers. They are ordered by that cost:
--
--     view 1 · like 3 · comment 6 · share 10
--
-- These are a starting point, not a truth. They are named here so changing
-- them is an edit to one line, and so nobody has to reverse-engineer them from
-- a ranking that looks odd.
--
-- DIVIDED BY THE WINDOW, so the result is per second — "interações por
-- segundo", as specified. A post's score does not grow simply by existing
-- longer.
CREATE OR REPLACE FUNCTION trending_posts(
    p_window INTERVAL DEFAULT INTERVAL '1 hour',
    p_limit  INT      DEFAULT 20,
    p_competition_id UUID DEFAULT NULL
)
RETURNS TABLE (
    post_id        UUID,
    views          BIGINT,
    likes          BIGINT,
    comments       BIGINT,
    shares         BIGINT,
    score_per_sec  NUMERIC
)
LANGUAGE sql STABLE AS
$$
    WITH since AS (SELECT NOW() - p_window AS ts)
    SELECT
        p.id,
        COALESCE(v.views, 0),
        COALESCE(l.n, 0),
        COALESCE(c.n, 0),
        COALESCE(s.n, 0),
        ROUND(
            (COALESCE(v.views, 0) * 1
           + COALESCE(l.n, 0)     * 3
           + COALESCE(c.n, 0)     * 6
           + COALESCE(s.n, 0)     * 10
            )::numeric / GREATEST(EXTRACT(EPOCH FROM p_window), 1),
        6)
    FROM posts p
    LEFT JOIN LATERAL (
        SELECT SUM(b.views) AS views FROM post_view_buckets b, since
         WHERE b.post_id = p.id AND b.bucket_start >= since.ts
    ) v ON TRUE
    LEFT JOIN LATERAL (
        SELECT count(*) AS n FROM post_likes x, since
         WHERE x.post_id = p.id AND x.created_at >= since.ts
    ) l ON TRUE
    LEFT JOIN LATERAL (
        SELECT count(*) AS n FROM comments x, since
         WHERE x.post_id = p.id AND x.created_at >= since.ts
    ) c ON TRUE
    LEFT JOIN LATERAL (
        SELECT count(*) AS n FROM post_shares x, since
         WHERE x.post_id = p.id AND x.created_at >= since.ts
    ) s ON TRUE
    WHERE p.deleted_at IS NULL
      AND p.visibility = 'public'
      -- The rail's selection reaches Explorar too: "em alta" in the
      -- competition you are looking at, not across the whole platform.
      AND (p_competition_id IS NULL OR p.competition_id = p_competition_id)
      -- Posts with no engagement in the window are not "em alta"; without
      -- this every dormant post is scanned and scored zero.
      AND (COALESCE(v.views, 0) + COALESCE(l.n, 0)
         + COALESCE(c.n, 0) + COALESCE(s.n, 0)) > 0
    ORDER BY 6 DESC, p.created_at DESC
    LIMIT GREATEST(p_limit, 1);
$$;

-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin
DROP FUNCTION IF EXISTS trending_posts(INTERVAL, INT, UUID);
DROP FUNCTION IF EXISTS record_post_views(UUID, BIGINT, BIGINT);
DROP FUNCTION IF EXISTS post_view_bucket(TIMESTAMPTZ);
DROP TABLE IF EXISTS post_view_buckets;
-- +goose StatementEnd
