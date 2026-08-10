import { Injectable } from '@nestjs/common';

import { DatabaseService } from '../db/database.service';

/**
 * Operational deadlines, and how close they are.
 *
 * The status is computed here rather than stored, for the same reason the due
 * date is computed in SQL: a cached "warning" is a claim about a moment that
 * has already passed by the time anyone reads it.
 */
export type ReminderStatus = 'ok' | 'due' | 'overdue' | 'unknown' | 'muted';

export interface Reminder {
  readonly id: string;
  readonly slug: string;
  readonly title: string;
  readonly impact: string;
  readonly kind: 'derived' | 'declared';
  readonly dueAt: string | null;
  readonly status: ReminderStatus;
  readonly daysRemaining: number | null;
  readonly leadDays: number;
  readonly periodDays: number | null;
  readonly lastDoneAt: string | null;
  readonly observedAt: string | null;
  readonly observedDetail: string | null;
  readonly mutedUntil: string | null;
  readonly notes: string | null;
  readonly updatedBy: string | null;
}

interface Row {
  id: string;
  slug: string;
  title: string;
  impact: string;
  kind: 'derived' | 'declared';
  due_at: Date | null;
  lead_days: number;
  period_days: number | null;
  last_done_at: Date | null;
  observed_at: Date | null;
  observed_detail: string | null;
  muted_until: Date | null;
  notes: string | null;
  updated_by: string | null;
}

/**
 * ISO-8601 with an explicit offset, and nothing else.
 *
 * `new Date()` alone accepts "Nov 10 2028" — which V8 parses in the
 * SERVER's timezone. A certificate expiry is an instant, and reading it as
 * local time shifts a deadline by hours depending on where the container
 * happens to run. Demanding the offset makes that impossible rather than
 * merely unlikely.
 *
 * Lives here rather than in the controller because the CLI reporter needs
 * the same rule, and a second copy is a second thing to loosen.
 */
const ISO_8601 =
  /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$/;

export function parseInstant(value: unknown): Date | null {
  if (typeof value !== 'string' || !ISO_8601.test(value.trim())) {
    return null;
  }
  const parsed = new Date(value.trim());
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

const SELECT = `
  SELECT r.id::text, r.slug, r.title, r.impact, r.kind,
         control_plane.reminder_due_at(
           r.kind, r.observed_expires_at, r.period_days, r.last_done_at
         ) AS due_at,
         r.lead_days, r.period_days, r.last_done_at,
         r.observed_at, r.observed_detail, r.muted_until, r.notes, r.updated_by
    FROM control_plane.operational_reminders r
`;

/**
 * The same columns, returned BY the write itself.
 *
 * This replaced `WITH updated AS (UPDATE … RETURNING id) SELECT … WHERE id
 * IN (SELECT id FROM updated)`, which is wrong in a way that looks right:
 * a data-modifying CTE and the query around it share one snapshot, so the
 * SELECT reads the row as it was BEFORE the UPDATE. Every write answered
 * with its own pre-image.
 *
 * Nothing failed. The rows were correct in the database and the page
 * reloads after each action, so the screen showed the truth either way —
 * the only visible trace was `reminders:report` printing "expires null
 * (unknown)" for a report that had, in fact, just landed. Caught by
 * running it against production, not by any test: a stubbed database
 * returns whatever the stub was told to.
 *
 * RETURNING on the statement itself sees the new row, which is what was
 * meant all along.
 */
const RETURNING = `
  RETURNING id::text, slug, title, impact, kind,
            control_plane.reminder_due_at(
              kind, observed_expires_at, period_days, last_done_at
            ) AS due_at,
            lead_days, period_days, last_done_at,
            observed_at, observed_detail, muted_until, notes, updated_by
`;

@Injectable()
export class RemindersService {
  constructor(private readonly db: DatabaseService) {}

  async list(): Promise<Reminder[]> {
    const rows = await this.db.query<Row>(
      // Ordered by urgency, not by name. The page exists to answer "what
      // needs attention", and a list an operator has to scan to find the
      // overdue item is a list that gets skimmed.
      `${SELECT} ORDER BY control_plane.reminder_due_at(
           r.kind, r.observed_expires_at, r.period_days, r.last_done_at
         ) ASC NULLS LAST`,
    );
    return rows.map((row) => this.present(row));
  }

  async findBySlug(slug: string): Promise<Reminder | null> {
    const rows = await this.db.query<Row>(`${SELECT} WHERE r.slug = $1`, [slug]);
    return rows.length ? this.present(rows[0]) : null;
  }

  /**
   * Create a DECLARED reminder — a policy the operator states.
   *
   * Derived reminders are deliberately not creatable here. One created
   * from the page would have nothing reporting into it, so it would sit at
   * `unknown` forever: the artefact has to gain a reporter before the
   * reminder means anything, and that is code, not a form.
   */
  async createDeclared(input: {
    slug: string;
    title: string;
    impact: string;
    periodDays: number;
    leadDays: number;
    notes: string | null;
    lastDoneAt: Date | null;
    operator: string;
  }): Promise<Reminder | null> {
    const rows = await this.db.query<Row>(
      `INSERT INTO control_plane.operational_reminders
         (slug, title, impact, kind, period_days, lead_days, notes,
          last_done_at, updated_by)
       VALUES ($1, $2, $3, 'declared', $4, $5, $6, $7, $8)
       ON CONFLICT (slug) DO NOTHING
       ${RETURNING}`,
      [
        input.slug,
        input.title,
        input.impact,
        input.periodDays,
        input.leadDays,
        input.notes,
        input.lastDoneAt,
        input.operator,
      ],
    );
    // Empty means the slug was taken. The caller turns that into a 409
    // rather than an overwrite: two operators naming the same policy
    // differently should collide loudly, not silently replace each other.
    return rows.length ? this.present(rows[0]) : null;
  }

  /**
   * Report an artefact's real expiry. Called by whatever OWNS the artefact —
   * the host holding the certificate — not by the console.
   *
   * Idempotent by slug: reporting the same expiry twice is the normal case
   * for a job that runs on a schedule.
   */
  async report(
    slug: string,
    expiresAt: Date,
    detail: string | null,
  ): Promise<Reminder | null> {
    const rows = await this.db.query<Row>(
      `UPDATE control_plane.operational_reminders
          SET observed_expires_at = $2,
              observed_at = now(),
              observed_detail = $3,
              updated_at = now()
        WHERE slug = $1 AND kind = 'derived'
        ${RETURNING}`,
      [slug, expiresAt, detail],
    );
    return rows.length ? this.present(rows[0]) : null;
  }

  /** Record that a declared reminder was done, which restarts its period. */
  async markDone(
    slug: string,
    operator: string,
    at: Date,
  ): Promise<Reminder | null> {
    const rows = await this.db.query<Row>(
      `UPDATE control_plane.operational_reminders
          SET last_done_at = $2, updated_at = now(), updated_by = $3
        WHERE slug = $1 AND kind = 'declared'
        ${RETURNING}`,
      [slug, at, operator],
    );
    return rows.length ? this.present(rows[0]) : null;
  }

  /**
   * Silence a reminder until a date, or `null` to un-silence it now.
   *
   * Bounded on purpose: an indefinite mute is a deletion that still occupies
   * a row, and the thing it was warning about does not stop being true.
   *
   * The `null` case is not symmetry for its own sake. Without it a mute is
   * a one-way door — the endpoint refuses a date in the past, so an
   * operator who silenced the wrong row, or silenced it for too long, has
   * no way back through the API. Un-silencing goes through this same
   * governed path, so choosing to look again is recorded exactly like
   * choosing to look away.
   */
  async mute(
    slug: string,
    until: Date | null,
    operator: string,
    notes: string | null,
  ): Promise<Reminder | null> {
    const rows = await this.db.query<Row>(
      `UPDATE control_plane.operational_reminders
          SET muted_until = $2, updated_at = now(), updated_by = $3,
              notes = COALESCE($4, notes)
        WHERE slug = $1
        ${RETURNING}`,
      [slug, until, operator, notes],
    );
    return rows.length ? this.present(rows[0]) : null;
  }

  private present(row: Row): Reminder {
    const now = Date.now();
    const due = row.due_at ? row.due_at.getTime() : null;
    // TRUNC, not floor. A reminder that is due at this instant is a
    // fraction of a day past its date, and floor turns that into -1 —
    // "venceu há 1 dia" for something that came due seconds ago. Trunc
    // reads the whole days that have actually elapsed, in both
    // directions.
    const daysRemaining =
      due === null ? null : Math.trunc((due - now) / 86_400_000);

    let status: ReminderStatus;
    if (row.muted_until && row.muted_until.getTime() > now) {
      status = 'muted';
    } else if (due === null) {
      // A derived reminder nobody has reported yet. NOT "ok": the deadline
      // exists whether or not anything has told us about it, and showing it
      // as fine would be the silence that this feature exists to break.
      status = 'unknown';
    } else if (due <= now) {
      status = 'overdue';
    } else if (daysRemaining !== null && daysRemaining <= row.lead_days) {
      status = 'due';
    } else {
      status = 'ok';
    }

    return {
      id: row.id,
      slug: row.slug,
      title: row.title,
      impact: row.impact,
      kind: row.kind,
      dueAt: row.due_at ? row.due_at.toISOString() : null,
      status,
      daysRemaining,
      leadDays: row.lead_days,
      periodDays: row.period_days,
      lastDoneAt: row.last_done_at ? row.last_done_at.toISOString() : null,
      observedAt: row.observed_at ? row.observed_at.toISOString() : null,
      observedDetail: row.observed_detail,
      mutedUntil: row.muted_until ? row.muted_until.toISOString() : null,
      notes: row.notes,
      updatedBy: row.updated_by,
    };
  }
}
