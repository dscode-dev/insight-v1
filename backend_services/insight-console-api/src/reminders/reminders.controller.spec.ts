import { BadRequestException, ForbiddenException } from '@nestjs/common';

import { IDENTITY_REQUEST_KEY, RequestWithIdentity } from '../identity/identity.guard';
import { RemindersController } from './reminders.controller';
import { Reminder, RemindersService } from './reminders.service';

function requestAs(role: string): RequestWithIdentity {
  return {
    [IDENTITY_REQUEST_KEY]: {
      operator: {
        id: 'op-1',
        username: 'ninja',
        email: 'n@example.com',
        displayName: 'Ninja',
        role,
        permissions: [],
        isActive: true,
      },
      token: 't',
    },
  } as unknown as RequestWithIdentity;
}

const REMINDER = { slug: 's', kind: 'declared' } as unknown as Reminder;

function controllerWith(overrides: Partial<RemindersService> = {}) {
  const service = {
    list: () => Promise.resolve([]),
    findBySlug: () => Promise.resolve(null),
    createDeclared: () => Promise.resolve(REMINDER),
    report: () => Promise.resolve(REMINDER),
    markDone: () => Promise.resolve(REMINDER),
    mute: () => Promise.resolve(REMINDER),
    ...overrides,
  } as unknown as RemindersService;
  return new RemindersController(service);
}

describe('RemindersController authorization', () => {
  it.each(['ReadOnly', 'Support', 'Moderator'])(
    'refuses %s on a write: config.write is what gates these',
    async (role) => {
      const controller = controllerWith();
      await expect(
        controller.markDone(requestAs(role), 'cloudflare-service-token'),
      ).rejects.toBeInstanceOf(ForbiddenException);
    },
  );

  it.each(['SuperAdmin', 'PlatformAdmin', 'MLAdmin'])(
    'allows %s',
    async (role) => {
      const controller = controllerWith();
      await expect(
        controller.markDone(requestAs(role), 'cloudflare-service-token'),
      ).resolves.toBe(REMINDER);
    },
  );

  it('refuses when the guard left no identity, rather than writing anonymously', async () => {
    const controller = controllerWith();
    await expect(
      controller.markDone({} as RequestWithIdentity, 's'),
    ).rejects.toBeInstanceOf(BadRequestException);
  });
});

describe('RemindersController validation', () => {
  const admin = () => requestAs('SuperAdmin');

  it('refuses a lead that is not shorter than the period', async () => {
    // Otherwise the reminder is amber from the moment it is marked done,
    // and an always-amber row teaches operators to ignore the colour.
    const controller = controllerWith();
    await expect(
      controller.create(admin(), {
        slug: 'rotate-thing',
        title: 't',
        impact: 'i',
        periodDays: 30,
        leadDays: 30,
      }),
    ).rejects.toBeInstanceOf(BadRequestException);
  });

  it.each([
    ['Rotate Thing', 'uppercase'],
    ['a', 'too short'],
    ['-leading', 'leading dash'],
    ['trailing-', 'trailing dash'],
    ['has_underscore', 'underscore'],
  ])('refuses slug %s (%s)', async (slug) => {
    const controller = controllerWith();
    await expect(
      controller.create(admin(), {
        slug,
        title: 't',
        impact: 'i',
        periodDays: 90,
        leadDays: 7,
      }),
    ).rejects.toBeInstanceOf(BadRequestException);
  });

  it('refuses a mute that is already over', async () => {
    const controller = controllerWith();
    await expect(
      controller.mute(admin(), 's', { until: '2020-01-01T00:00:00Z' }),
    ).rejects.toBeInstanceOf(BadRequestException);
  });

  /**
   * Un-silencing has to be reachable. A past date is refused and there is
   * no separate endpoint, so without `until: null` a mute would be a
   * one-way door — and it goes through this same governed path, so
   * choosing to look again is recorded like choosing to look away.
   */
  it('accepts until: null to clear a mute', async () => {
    let seen: unknown = 'unset';
    const controller = controllerWith({
      mute: (_slug: string, until: Date | null) => {
        seen = until;
        return Promise.resolve(REMINDER);
      },
    } as unknown as Partial<RemindersService>);
    await expect(controller.mute(admin(), 's', { until: null })).resolves.toBe(
      REMINDER,
    );
    expect(seen).toBeNull();
  });

  it('still refuses a missing until — omitting it is not the same as clearing', async () => {
    const controller = controllerWith();
    await expect(controller.mute(admin(), 's', {})).rejects.toBeInstanceOf(
      BadRequestException,
    );
  });

  /**
   * `new Date('Nov 10 2028')` succeeds — in the SERVER's timezone. That is
   * the dangerous case, not the garbage one: it produces a plausible date
   * that is hours off, which no reader would question.
   */
  it.each([
    ['Nov 10 2028', 'openssl format, parsed as local time'],
    ['2028-11-10T04:12:31', 'ISO but with no offset'],
    ['2028-11-10', 'date only'],
    ['amanha', 'not a date at all'],
    [1_800_000_000_000, 'epoch millis'],
  ] as [string | number, string][])('refuses expiry %p (%s)', async (expiresAt) => {
    const controller = controllerWith();
    await expect(
      controller.report(admin(), 's', { expiresAt }),
    ).rejects.toBeInstanceOf(BadRequestException);
  });

  it.each(['2028-11-10T04:12:31Z', '2028-11-10T01:12:31-03:00'])(
    'accepts %s',
    async (expiresAt) => {
      const controller = controllerWith();
      await expect(
        controller.report(admin(), 's', { expiresAt }),
      ).resolves.toBe(REMINDER);
    },
  );

  it('defaults leadDays to 30 when omitted', async () => {
    let seen: { leadDays?: number } = {};
    const controller = controllerWith({
      createDeclared: (input: { leadDays: number }) => {
        seen = input;
        return Promise.resolve(REMINDER);
      },
    } as unknown as Partial<RemindersService>);
    await controller.create(admin(), {
      slug: 'rotate-thing',
      title: 't',
      impact: 'i',
      periodDays: 90,
    });
    expect(seen.leadDays).toBe(30);
  });

  /**
   * "Not found" and "wrong kind" are the same empty result from the same
   * UPDATE. Answering the first for the second sends whoever wrote the
   * reporter hunting for a typo in a slug that is correct.
   */
  it('says kind mismatch, not not_found, when the slug exists as the other kind', async () => {
    const controller = controllerWith({
      report: () => Promise.resolve(null),
      findBySlug: () =>
        Promise.resolve({ kind: 'declared' } as unknown as Reminder),
    } as unknown as Partial<RemindersService>);
    await expect(
      controller.report(admin(), 'cloudflare-service-token', {
        expiresAt: '2028-11-10T00:00:00Z',
      }),
    ).rejects.toMatchObject({
      response: {
        message: 'reminder_kind_mismatch:expected_derived_got_declared',
      },
    });
  });
});

describe('RemindersController list', () => {
  it('summarises by status so the page can lead with what is wrong', async () => {
    const controller = controllerWith({
      list: () =>
        Promise.resolve([
          { status: 'overdue' },
          { status: 'due' },
          { status: 'due' },
          { status: 'ok' },
          { status: 'unknown' },
        ] as unknown as Reminder[]),
    } as unknown as Partial<RemindersService>);
    const { summary } = await controller.list();
    expect(summary).toEqual({ overdue: 1, due: 2, ok: 1, unknown: 1, muted: 0 });
  });
});
