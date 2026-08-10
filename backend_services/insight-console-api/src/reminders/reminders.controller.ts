import {
  BadRequestException,
  Body,
  ConflictException,
  Controller,
  ForbiddenException,
  Get,
  HttpCode,
  NotFoundException,
  Param,
  Post,
  Req,
} from '@nestjs/common';

import {
  IDENTITY_REQUEST_KEY,
  RequestWithIdentity,
} from '../identity/identity.guard';
import { permissionsForRole } from '../identity/rbac';
import {
  parseInstant,
  Reminder,
  RemindersService,
} from './reminders.service';

interface CreateBody {
  slug?: unknown;
  title?: unknown;
  impact?: unknown;
  periodDays?: unknown;
  leadDays?: unknown;
  notes?: unknown;
  lastDoneAt?: unknown;
}

interface MuteBody {
  until?: unknown;
  notes?: unknown;
}

interface ObservedBody {
  expiresAt?: unknown;
  detail?: unknown;
}

const SLUG = /^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/;

@Controller('reminders')
export class RemindersController {
  constructor(private readonly reminders: RemindersService) {}

  @Get()
  async list(): Promise<{
    reminders: Reminder[];
    summary: Record<string, number>;
  }> {
    const reminders = await this.reminders.list();
    const summary = { overdue: 0, due: 0, unknown: 0, muted: 0, ok: 0 };
    for (const reminder of reminders) {
      summary[reminder.status] += 1;
    }
    return { reminders, summary };
  }

  @Post()
  @HttpCode(201)
  async create(
    @Req() request: RequestWithIdentity,
    @Body() body: CreateBody,
  ): Promise<Reminder> {
    const operator = writerOf(request);

    const slug = text(body?.slug, 'slug');
    if (!SLUG.test(slug)) {
      throw new BadRequestException('invalid_slug');
    }
    const periodDays = integer(body?.periodDays, 'periodDays', 1, 3650);
    const leadDays =
      body?.leadDays === undefined || body.leadDays === null
        ? 30
        : integer(body.leadDays, 'leadDays', 0, 365);
    if (leadDays >= periodDays) {
      // A lead longer than the period means the reminder is due from the
      // moment it is recorded as done — permanently amber, which trains
      // operators to ignore the colour.
      throw new BadRequestException('lead_days_must_be_below_period_days');
    }

    const created = await this.reminders.createDeclared({
      slug,
      title: text(body?.title, 'title'),
      impact: text(body?.impact, 'impact'),
      periodDays,
      leadDays,
      notes: optionalText(body?.notes),
      lastDoneAt: body?.lastDoneAt ? date(body.lastDoneAt, 'lastDoneAt') : null,
      operator,
    });
    if (created === null) {
      throw new ConflictException('reminder_slug_taken');
    }
    return created;
  }

  /**
   * Record that a declared reminder was done. Restarts its period.
   *
   * Always stamped with `now()` on this side: accepting a caller-supplied
   * timestamp would let a rotation be backdated, and the whole value of the
   * row is that the date reflects something that actually happened.
   */
  // 200, not Nest's default 201 for POST: these update a row that
  // already exists. Only the collection POST creates anything.
  @Post(':slug/done')
  @HttpCode(200)
  async markDone(
    @Req() request: RequestWithIdentity,
    @Param('slug') slug: string,
  ): Promise<Reminder> {
    const operator = writerOf(request);
    const updated = await this.reminders.markDone(slug, operator, new Date());
    if (updated === null) {
      throw new NotFoundException(await this.explainMiss(slug, 'declared'));
    }
    return updated;
  }

  @Post(':slug/mute')
  @HttpCode(200)
  async mute(
    @Req() request: RequestWithIdentity,
    @Param('slug') slug: string,
    @Body() body: MuteBody,
  ): Promise<Reminder> {
    const operator = writerOf(request);
    // `until: null` clears the mute. Without it, muting is a one-way door:
    // a past date is refused, so nothing could ever un-silence a row.
    const until =
      body?.until === null ? null : date(body?.until, 'until');
    if (until !== null && until.getTime() <= Date.now()) {
      throw new BadRequestException('mute_until_must_be_in_the_future');
    }
    const updated = await this.reminders.mute(
      slug,
      until,
      operator,
      optionalText(body?.notes),
    );
    if (updated === null) {
      throw new NotFoundException('reminder_not_found');
    }
    return updated;
  }

  /**
   * Report an observed expiry for a derived reminder.
   *
   * The caller is whatever holds the artefact. It still arrives with an
   * operator session, because this service has exactly one unauthenticated
   * surface (the healthcheck) and widening that for a reporter would be a
   * larger change than the reporter is worth. The automated path is
   * `node dist/cli.js reminders:report`, which runs inside this image and
   * goes through the same service method.
   */
  @Post(':slug/observed')
  @HttpCode(200)
  async report(
    @Req() request: RequestWithIdentity,
    @Param('slug') slug: string,
    @Body() body: ObservedBody,
  ): Promise<Reminder> {
    writerOf(request);
    const updated = await this.reminders.report(
      slug,
      date(body?.expiresAt, 'expiresAt'),
      optionalText(body?.detail),
    );
    if (updated === null) {
      throw new NotFoundException(await this.explainMiss(slug, 'derived'));
    }
    return updated;
  }

  /**
   * Separate "no such reminder" from "wrong kind".
   *
   * Both are a miss on the same UPDATE, and answering `reminder_not_found`
   * to someone reporting an expiry against a declared reminder would send
   * them looking for a typo in the slug instead of at the mismatch.
   */
  private async explainMiss(
    slug: string,
    expected: 'derived' | 'declared',
  ): Promise<string> {
    const existing = await this.reminders.findBySlug(slug);
    if (existing === null) {
      return 'reminder_not_found';
    }
    return `reminder_kind_mismatch:expected_${expected}_got_${existing.kind}`;
  }
}

function writerOf(request: RequestWithIdentity): string {
  const identity = request[IDENTITY_REQUEST_KEY];
  const operator = identity?.operator;
  if (!operator) {
    throw new BadRequestException('operator_identity_missing');
  }
  if (!permissionsForRole(operator.role).includes('config.write')) {
    throw new ForbiddenException('config.write required');
  }
  return operator.username || operator.id;
}

function text(value: unknown, field: string): string {
  const trimmed = typeof value === 'string' ? value.trim() : '';
  if (!trimmed || trimmed.length > 500) {
    throw new BadRequestException(`invalid_${field}`);
  }
  return trimmed;
}

function optionalText(value: unknown): string | null {
  if (value === undefined || value === null || value === '') {
    return null;
  }
  return text(value, 'notes');
}

function integer(
  value: unknown,
  field: string,
  min: number,
  max: number,
): number {
  const parsed = typeof value === 'number' ? value : Number(value);
  if (!Number.isInteger(parsed) || parsed < min || parsed > max) {
    throw new BadRequestException(`invalid_${field}`);
  }
  return parsed;
}

function date(value: unknown, field: string): Date {
  const parsed = parseInstant(value);
  if (parsed === null) {
    throw new BadRequestException(`invalid_${field}`);
  }
  return parsed;
}
