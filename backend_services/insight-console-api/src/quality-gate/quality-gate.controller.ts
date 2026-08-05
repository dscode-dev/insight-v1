import {
  BadRequestException,
  Body,
  ConflictException,
  Controller,
  Delete,
  Get,
  HttpCode,
  Param,
  Post,
  Query,
  Req,
} from '@nestjs/common';

import {
  IDENTITY_REQUEST_KEY,
  RequestWithIdentity,
} from '../identity/identity.guard';
import { UpstreamError } from '../upstream/upstream.service';
import {
  Decision,
  DecisionInput,
  ReplayReview,
  ReplaySubmission,
} from './quality-gate.contracts';
import { QualityGateService } from './quality-gate.service';

const SOURCES = new Set([
  'match',
  'competition',
  'season',
  'interval',
  'dataset',
  'mission',
]);

@Controller('quality-gate')
export class QualityGateController {
  constructor(private readonly gate: QualityGateService) {}

  @Get('replays')
  listReplays(@Query('limit') limit?: string): Promise<Record<string, unknown>> {
    return this.gate.listReplays(clampLimit(limit));
  }

  @Post('replays')
  @HttpCode(202)
  submitReplay(
    @Req() request: RequestWithIdentity,
    @Body() body: ReplaySubmission,
  ): Promise<Record<string, unknown>> {
    if (!body || !SOURCES.has(body.source)) {
      throw new BadRequestException('invalid_replay_source');
    }
    return this.gate.submitReplay(actorOf(request), body);
  }

  @Get('replays/:id')
  review(@Param('id') id: string): Promise<ReplayReview> {
    return this.gate.review(id);
  }

  @Delete('replays/:id')
  cancel(
    @Req() request: RequestWithIdentity,
    @Param('id') id: string,
  ): Promise<Record<string, unknown>> {
    return this.gate.cancelReplay(actorOf(request), id);
  }

  @Get('decisions')
  listDecisions(@Query('limit') limit?: string): Promise<Record<string, unknown>> {
    return this.gate.listDecisions(clampLimit(limit));
  }

  /**
   * Record the human approve/reject that ATLAS_V1_FROZEN.md requires.
   *
   * Any `decided_by` in the body is ignored: attribution comes from the
   * verified identity envelope. An approval attributable to whoever
   * sent the request would make the whole audit trail worthless.
   */
  @Post('replays/:id/decision')
  @HttpCode(201)
  async decide(
    @Req() request: RequestWithIdentity,
    @Param('id') id: string,
    @Body() body: DecisionInput,
  ): Promise<Decision> {
    if (!body || (body.verdict !== 'approved' && body.verdict !== 'rejected')) {
      throw new BadRequestException('invalid_verdict');
    }
    if (typeof body.reason !== 'string' || body.reason.trim().length === 0) {
      throw new BadRequestException('reason_required');
    }
    try {
      return await this.gate.decide(actorOf(request), id, {
        verdict: body.verdict,
        reason: body.reason,
        override_recommendation: body.override_recommendation === true,
        acknowledge_no_baseline: body.acknowledge_no_baseline === true,
      });
    } catch (error) {
      // Translate the gate's refusal into something the screen can act
      // on. Without the code the operator sees a bare failure and has
      // no way to learn that an explicit override is what's missing.
      if (error instanceof UpstreamError && error.refusal) {
        throw new ConflictException({
          code: error.refusal.code,
          message: error.refusal.message,
        });
      }
      throw error;
    }
  }
}

function actorOf(request: RequestWithIdentity): string {
  const identity = request[IDENTITY_REQUEST_KEY];
  // The global IdentityGuard populates this before any handler runs, so
  // an empty value here means the guard was bypassed — refuse rather
  // than recording an unattributed decision.
  const actor = identity?.operatorUsername || identity?.operatorId || '';
  if (!actor) {
    throw new BadRequestException('operator_identity_missing');
  }
  return actor;
}

function clampLimit(raw: string | undefined): number {
  const parsed = Number(raw ?? '50');
  if (!Number.isFinite(parsed)) {
    return 50;
  }
  return Math.min(500, Math.max(1, Math.trunc(parsed)));
}
