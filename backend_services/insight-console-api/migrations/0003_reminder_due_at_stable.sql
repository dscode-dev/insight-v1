--
-- `control_plane.reminder_due_at` was declared IMMUTABLE and contains
-- `now()`. Those cannot both be true.
--
-- IMMUTABLE is a PROMISE to the planner: same arguments, same answer,
-- forever. It licenses constant-folding the call at plan time and reusing
-- that value from the plan cache. The function's `p_last_done_at IS NULL
-- THEN now()` branch — a declared reminder nobody has ever done, which is
-- due immediately — would then be frozen at whatever moment the plan was
-- first built, in a process that stays up for weeks.
--
-- Nothing had gone wrong yet: the reminders seeded so far all carry a
-- last_done_at or an observed expiry, so the `now()` branch never ran, and
-- with three rows there was no reason for the planner to fold anything.
-- It would have surfaced as a reminder that quietly stops advancing —
-- which is the one failure this whole feature exists to prevent.
--
-- STABLE is the honest declaration: constant within a statement, free to
-- differ between statements. It still permits index use in a WHERE
-- clause, so nothing is given up here.
--
-- 0002 keeps the wrong word. The migrator refuses any file whose checksum
-- no longer matches what was applied — correctly, since an edited
-- migration means the database and the file disagree — so the fix has to
-- arrive as a new file, and the history keeps the mistake visible.
--
CREATE OR REPLACE FUNCTION control_plane.reminder_due_at(
    p_kind TEXT,
    p_observed_expires_at TIMESTAMPTZ,
    p_period_days INTEGER,
    p_last_done_at TIMESTAMPTZ
) RETURNS TIMESTAMPTZ
LANGUAGE sql STABLE AS
$$
    SELECT CASE
        WHEN p_kind = 'derived' THEN p_observed_expires_at
        -- A declared reminder that has never been done is due now: it was
        -- created because something needs doing, and treating "no record"
        -- as "no deadline" would hide exactly the ones nobody has started.
        WHEN p_last_done_at IS NULL THEN now()
        ELSE p_last_done_at + make_interval(days => p_period_days)
    END
$$;
