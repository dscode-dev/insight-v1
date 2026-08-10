import { DatabaseService } from '../db/database.service';
import { RemindersService } from './reminders.service';

/**
 * The status computation, against a stubbed database.
 *
 * These do NOT cover `control_plane.reminder_due_at` — that runs in
 * Postgres, and asserting it here would only test a reimplementation of
 * it. What is covered is the half that lives in TypeScript: turning a due
 * date into the word an operator reads.
 */
const DAY = 86_400_000;

function serviceReturning(rows: Record<string, unknown>[]): {
  service: RemindersService;
  calls: { sql: string; params: unknown[] }[];
} {
  const calls: { sql: string; params: unknown[] }[] = [];
  const db = {
    query: (sql: string, params: unknown[] = []) => {
      calls.push({ sql, params });
      return Promise.resolve(rows);
    },
  } as unknown as DatabaseService;
  return { service: new RemindersService(db), calls };
}

function row(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'id-1',
    slug: 'mtls-social-cert',
    title: 'Certificado',
    impact: 'o gRPC para',
    kind: 'derived',
    due_at: new Date(Date.now() + 400 * DAY),
    lead_days: 45,
    period_days: null,
    last_done_at: null,
    observed_at: new Date(),
    observed_detail: null,
    muted_until: null,
    notes: null,
    updated_by: null,
    ...overrides,
  };
}

describe('RemindersService status', () => {
  it('is ok while the deadline is further away than the lead', async () => {
    const { service } = serviceReturning([row()]);
    const [reminder] = await service.list();
    expect(reminder.status).toBe('ok');
    expect(reminder.daysRemaining).toBeGreaterThan(45);
  });

  it('turns due once inside the lead window', async () => {
    // Half a day off the boundary ON PURPOSE. At exactly +10d the floor
    // lands on 10 or 9 depending on whether a millisecond elapsed between
    // building the row and reading it — a test that fails once a week and
    // gets rerun rather than read.
    const { service } = serviceReturning([
      row({ due_at: new Date(Date.now() + 10.5 * DAY) }),
    ]);
    const [reminder] = await service.list();
    expect(reminder.status).toBe('due');
    expect(reminder.daysRemaining).toBe(10);
  });

  it('is overdue once the deadline has passed', async () => {
    const { service } = serviceReturning([
      row({ due_at: new Date(Date.now() - DAY) }),
    ]);
    const [reminder] = await service.list();
    expect(reminder.status).toBe('overdue');
    expect(reminder.daysRemaining).toBeLessThan(0);
  });

  /**
   * The one that matters. A derived reminder nobody has reported is the
   * exact state this feature exists to make visible — showing it as `ok`
   * would be the silence it was built to break.
   */
  it('is unknown, NOT ok, when nothing has reported an expiry', async () => {
    const { service } = serviceReturning([
      row({ due_at: null, observed_at: null }),
    ]);
    const [reminder] = await service.list();
    expect(reminder.status).toBe('unknown');
    expect(reminder.dueAt).toBeNull();
    expect(reminder.daysRemaining).toBeNull();
  });

  it('reports muted while the mute holds, and stops when it lapses', async () => {
    const overdue = { due_at: new Date(Date.now() - DAY) };
    const { service: muted } = serviceReturning([
      row({ ...overdue, muted_until: new Date(Date.now() + DAY) }),
    ]);
    expect((await muted.list())[0].status).toBe('muted');

    const { service: expired } = serviceReturning([
      row({ ...overdue, muted_until: new Date(Date.now() - DAY) }),
    ]);
    expect((await expired.list())[0].status).toBe('overdue');
  });

  it('boundary: exactly at the lead is due, one day past it is ok', async () => {
    const { service: atLead } = serviceReturning([
      // +45d minus a minute floors to 44 remaining, inside a 45d lead.
      row({ due_at: new Date(Date.now() + 45 * DAY - 60_000) }),
    ]);
    expect((await atLead.list())[0].status).toBe('due');

    const { service: beyond } = serviceReturning([
      row({ due_at: new Date(Date.now() + 46 * DAY + 60_000) }),
    ]);
    expect((await beyond.list())[0].status).toBe('ok');
  });
});

describe('RemindersService writes', () => {
  it('reports only against derived reminders', async () => {
    const { service, calls } = serviceReturning([row()]);
    await service.report('mtls-social-cert', new Date('2028-11-10T00:00:00Z'), 'x');
    expect(calls[0].sql).toContain("kind = 'derived'");
    expect(calls[0].params[0]).toBe('mtls-social-cert');
  });

  it('marks done only against declared reminders', async () => {
    const { service, calls } = serviceReturning([
      row({ kind: 'declared', period_days: 90 }),
    ]);
    await service.markDone('cloudflare-service-token', 'ninja', new Date());
    expect(calls[0].sql).toContain("kind = 'declared'");
  });

  /**
   * A miss must be distinguishable from a hit. Both UPDATEs are scoped by
   * kind, so reporting against the wrong kind updates nothing — and if
   * that returned a reminder anyway, a drifted reporter would look
   * healthy while never refreshing anything.
   */
  it('returns null when the update matched nothing', async () => {
    const { service } = serviceReturning([]);
    expect(await service.report('nope', new Date(), null)).toBeNull();
    expect(await service.markDone('nope', 'ninja', new Date())).toBeNull();
    expect(await service.mute('nope', new Date(), 'ninja', null)).toBeNull();
  });

  it('leaves notes untouched when a mute carries none', async () => {
    const { service, calls } = serviceReturning([row()]);
    await service.mute('mtls-social-cert', new Date(), 'ninja', null);
    expect(calls[0].sql).toContain('COALESCE($4, notes)');
    expect(calls[0].params[3]).toBeNull();
  });

  /**
   * Every write must answer with the row it just produced.
   *
   * The first version wrapped each write in `WITH updated AS (UPDATE …
   * RETURNING id) SELECT … WHERE id IN (SELECT id FROM updated)`, which
   * reads correct and is not: a data-modifying CTE and the query around
   * it share one snapshot, so the SELECT returns the row as it was BEFORE
   * the write. Every write answered with its own pre-image, and nothing
   * failed — the database was right, the page reloads, and only
   * `reminders:report` printing "expires null" gave it away.
   *
   * A stubbed database cannot catch that (it returns whatever it was
   * told), so this asserts the SHAPE instead: writes use RETURNING, never
   * a re-SELECT through a CTE.
   */
  it.each([
    [
      'report',
      (service: RemindersService) => service.report('s', new Date(), null),
    ],
    [
      'markDone',
      (service: RemindersService) => service.markDone('s', 'ninja', new Date()),
    ],
    [
      'mute',
      (service: RemindersService) => service.mute('s', new Date(), 'ninja', null),
    ],
    [
      'createDeclared',
      (service: RemindersService) =>
        service.createDeclared({
          slug: 's',
          title: 't',
          impact: 'i',
          periodDays: 90,
          leadDays: 7,
          notes: null,
          lastDoneAt: null,
          operator: 'ninja',
        }),
    ],
  ])('%s returns the post-write row, not a re-SELECT', async (_name, run) => {
    const { service, calls } = serviceReturning([row()]);
    await run(service);
    expect(calls).toHaveLength(1);
    expect(calls[0].sql).toContain('RETURNING');
    expect(calls[0].sql).not.toMatch(/WITH\s+\w+\s+AS\s*\(/i);
    // The computed due date has to come from the same statement, or the
    // caller gets a fresh row carrying a stale deadline.
    expect(calls[0].sql).toContain('reminder_due_at');
  });

  it('does not overwrite an existing slug on create', async () => {
    const { service, calls } = serviceReturning([]);
    const created = await service.createDeclared({
      slug: 'cloudflare-service-token',
      title: 't',
      impact: 'i',
      periodDays: 90,
      leadDays: 7,
      notes: null,
      lastDoneAt: null,
      operator: 'ninja',
    });
    expect(calls[0].sql).toContain('ON CONFLICT (slug) DO NOTHING');
    expect(created).toBeNull();
  });
});
