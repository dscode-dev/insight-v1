import { Injectable, Logger } from '@nestjs/common';

import { UpstreamError, UpstreamService } from '../upstream/upstream.service';
import {
  Decision,
  DecisionInput,
  QualityEvaluation,
  ReplayReview,
  ReplaySubmission,
  summarizeGate,
} from './quality-gate.contracts';

/**
 * Atlas Quality Gate — the human-approval path for promoting changes to
 * the frozen intelligence core.
 *
 * `ATLAS_V1_FROZEN.md` requires every new detector or heuristic to pass
 * the gate against the frozen baseline before promotion, and states
 * that human approval is mandatory. Atlas exposed the machinery
 * (`/backtests/*`) but nothing consumed it and there was no way for a
 * person to record a decision at all. This service is the console's
 * half of closing that.
 */
@Injectable()
export class QualityGateService {
  private readonly logger = new Logger(QualityGateService.name);

  constructor(private readonly upstream: UpstreamService) {}

  async listReplays(limit = 50): Promise<Record<string, unknown>> {
    return this.upstream.atlas({ path: `backtests?limit=${limit}` });
  }

  async submitReplay(
    actor: string,
    submission: ReplaySubmission,
  ): Promise<Record<string, unknown>> {
    return this.upstream.atlas({
      path: 'backtests',
      method: 'POST',
      // `requester` is attribution, so it comes from the verified
      // identity — never from the submitted body.
      body: { ...submission, requester: actor },
      actor,
    });
  }

  async cancelReplay(actor: string, id: string): Promise<Record<string, unknown>> {
    return this.upstream.atlas({
      path: `backtests/${encodeURIComponent(id)}`,
      method: 'DELETE',
      actor,
    });
  }

  /**
   * One replay, fully resolved: status + evaluation + manifest +
   * any recorded decision, with the gate rules already applied.
   *
   * The three sub-resources 404 legitimately while a replay is still
   * running, so a 404 is mapped to `null` rather than propagated —
   * "not finished yet" is not an error for this screen. Any OTHER
   * upstream failure still throws; degrading a 500 to `null` would
   * render an in-progress screen for a broken Atlas.
   */
  async review(id: string): Promise<ReplayReview> {
    const path = `backtests/${encodeURIComponent(id)}`;
    const execution = await this.upstream.atlas<Record<string, unknown>>({ path });

    const [quality, manifest, decision] = await Promise.all([
      this.optional<QualityEvaluation>(`${path}/quality`),
      this.optional<Record<string, unknown>>(`${path}/manifest`),
      this.optional<Decision>(`${path}/decision`),
    ]);

    return {
      execution,
      quality,
      manifest,
      decision,
      gate: summarizeGate(quality),
    };
  }

  async listDecisions(limit = 50): Promise<Record<string, unknown>> {
    return this.upstream.atlas({ path: `backtests/decisions?limit=${limit}` });
  }

  /**
   * Record the operator's approve/reject.
   *
   * `surfaceRefusal` is on because Atlas answers a blocked approval
   * with `409 {detail: {code: "override_required" | "baseline_required"
   * | "decision_exists", message}}`, and that code is the only thing
   * telling the operator what the gate wants from them. Swallowing it
   * would leave the screen showing an unexplained failure on the one
   * action the whole feature exists for.
   */
  async decide(
    actor: string,
    id: string,
    input: DecisionInput,
  ): Promise<Decision> {
    try {
      const decision = await this.upstream.atlas<Decision>({
        path: `backtests/${encodeURIComponent(id)}/decision`,
        method: 'POST',
        body: input,
        // Atlas derives `decided_by` from this header, not the body.
        actor,
        surfaceRefusal: true,
      });
      this.logger.log(
        `promotion decision recorded: ${input.verdict} on ${id} by ${actor}`,
      );
      return decision;
    } catch (error) {
      if (error instanceof UpstreamError && error.refusal) {
        this.logger.warn(
          `promotion decision refused (${error.refusal.code}) on ${id} by ${actor}`,
        );
      }
      throw error;
    }
  }

  private async optional<T>(path: string): Promise<T | null> {
    try {
      return await this.upstream.atlas<T>({ path });
    } catch (error) {
      if (error instanceof UpstreamError && error.status === 404) {
        return null;
      }
      throw error;
    }
  }
}
