import {
  BadRequestException,
  Body,
  Controller,
  Get,
  Param,
  Post,
  Query,
  Req,
} from '@nestjs/common';

import {
  IDENTITY_REQUEST_KEY,
  RequestWithIdentity,
} from '../identity/identity.guard';
import { ExplorerOpsService } from './explorer-ops.service';

const TASK_ACTIONS = new Set(['start', 'restart']);
const SCHEDULER_ACTIONS = new Set(['pause', 'resume', 'cancel']);

@Controller('explorer-ops')
export class ExplorerOpsController {
  constructor(private readonly ops: ExplorerOpsService) {}

  // -- review / curation ------------------------------------------------ //

  @Get('review')
  reviewQueue(
    @Query('status') status?: string,
    @Query('competition') competition?: string,
  ): Promise<unknown> {
    return this.ops.reviewQueue(status || 'pending', competition || undefined);
  }

  @Post('review/promote')
  promote(
    @Req() request: RequestWithIdentity,
    @Body() body: { external_id?: string },
  ): Promise<unknown> {
    return this.ops.reviewPromote(actorOf(request), requiredId(body?.external_id));
  }

  @Post('review/reject')
  reject(
    @Req() request: RequestWithIdentity,
    @Body() body: { external_id?: string },
  ): Promise<unknown> {
    return this.ops.reviewReject(actorOf(request), requiredId(body?.external_id));
  }

  @Post('review/replay')
  replay(
    @Req() request: RequestWithIdentity,
    @Body() body: { competition?: string; season?: string },
  ): Promise<unknown> {
    if (!body?.competition || !body?.season) {
      throw new BadRequestException('competition_and_season_required');
    }
    return this.ops.reviewReplay(actorOf(request), body.competition, body.season);
  }

  // -- jobs -------------------------------------------------------------- //

  @Get('jobs')
  jobs(@Query('limit') limit?: string): Promise<Record<string, unknown>> {
    return this.ops.jobsOverview(clampLimit(limit, 100, 1000));
  }

  @Get('jobs/:id')
  job(@Param('id') id: string): Promise<unknown> {
    return this.ops.job(id);
  }

  /**
   * Task-scoped: start/restart ONE (competition, season).
   *
   * Separate route from the scheduler controls below so a caller cannot
   * accidentally address a whole-scheduler action through the
   * task-shaped one.
   */
  @Post('jobs/task/:action')
  taskAction(
    @Req() request: RequestWithIdentity,
    @Param('action') action: string,
    @Body() body: { competition?: string; season?: string },
  ): Promise<unknown> {
    if (!TASK_ACTIONS.has(action)) {
      throw new BadRequestException('invalid_task_action');
    }
    if (!body?.competition || !body?.season) {
      throw new BadRequestException('competition_and_season_required');
    }
    return this.ops.taskAction(
      actorOf(request),
      action as 'start' | 'restart',
      body.competition,
      body.season,
    );
  }

  /** Scheduler-wide: pause/resume/cancel EVERYTHING. */
  @Post('scheduler/:action')
  schedulerAction(
    @Req() request: RequestWithIdentity,
    @Param('action') action: string,
  ): Promise<unknown> {
    if (!SCHEDULER_ACTIONS.has(action)) {
      throw new BadRequestException('invalid_scheduler_action');
    }
    return this.ops.schedulerAction(
      actorOf(request),
      action as 'pause' | 'resume' | 'cancel',
    );
  }

  // -- quality ----------------------------------------------------------- //

  @Get('quality')
  quality(): Promise<Record<string, unknown>> {
    return this.ops.qualityOverview();
  }

  // -- runtime ----------------------------------------------------------- //

  @Get('runtime')
  runtime(): Promise<unknown> {
    return this.ops.runtime();
  }

  @Post('runtime/reload')
  reload(@Req() request: RequestWithIdentity): Promise<unknown> {
    return this.ops.reloadRuntime(actorOf(request));
  }
}

function actorOf(request: RequestWithIdentity): string {
  const identity = request[IDENTITY_REQUEST_KEY];
  const actor = identity?.operatorUsername || identity?.operatorId || '';
  if (!actor) {
    // The global IdentityGuard fills this before any handler runs, so an
    // empty value means the guard was bypassed. Explorer records the
    // actor in its own audit log — an unattributed mutation is worse
    // than a refused one.
    throw new BadRequestException('operator_identity_missing');
  }
  return actor;
}

function requiredId(value: string | undefined): string {
  if (typeof value !== 'string' || value.trim().length === 0) {
    throw new BadRequestException('external_id_required');
  }
  return value.trim();
}

function clampLimit(raw: string | undefined, fallback: number, max: number): number {
  const parsed = Number(raw ?? String(fallback));
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(max, Math.max(1, Math.trunc(parsed)));
}
