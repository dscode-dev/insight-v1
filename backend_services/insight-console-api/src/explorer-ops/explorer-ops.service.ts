import { Injectable, Logger } from '@nestjs/common';

import { UpstreamService } from '../upstream/upstream.service';

/**
 * The Explorer surfaces that had no console consumer at all.
 *
 * The audit found 33 Explorer endpoints with zero UI. The four groups
 * covered here are the ones with real operational consequence:
 *
 *  * review/curation — a human promote/reject queue that was entirely
 *    unreachable, the same class of gap as the Quality Gate;
 *  * jobs — the collection workers, with no way to see or steer them;
 *  * quality — validation rates, entity resolution, duplicates;
 *  * runtime — scheduler/storage/config state.
 *
 * Composition happens here rather than in the browser so a screen makes
 * one call instead of fanning out to four endpoints that each need the
 * ops token.
 */
@Injectable()
export class ExplorerOpsService {
  private readonly logger = new Logger(ExplorerOpsService.name);

  constructor(private readonly upstream: UpstreamService) {}

  // -- review / curation ----------------------------------------------- //

  /**
   * The human curation queue plus its counters.
   *
   * Worth knowing when reading this screen: promoting a record appends
   * its envelope to the VALIDATED lake layer, which is exactly what
   * Atlas's `StrengthSyncWatcher` consumes. A promotion here feeds the
   * team-strength engine — curation is upstream of Atlas's ratings, not
   * a side ledger.
   */
  async reviewQueue(status = 'pending', competition?: string): Promise<unknown> {
    const params = new URLSearchParams({ status });
    if (competition) {
      params.set('competition', competition);
    }
    return this.upstream.explorer({ path: `review?${params.toString()}` });
  }

  async reviewPromote(actor: string, externalId: string): Promise<unknown> {
    this.logger.log(`review promote ${externalId} by ${actor}`);
    return this.upstream.explorer({
      path: 'review/promote',
      method: 'POST',
      body: { external_id: externalId },
      actor,
    });
  }

  async reviewReject(actor: string, externalId: string): Promise<unknown> {
    this.logger.log(`review reject ${externalId} by ${actor}`);
    return this.upstream.explorer({
      path: 'review/reject',
      method: 'POST',
      body: { external_id: externalId },
      actor,
    });
  }

  async reviewReplay(
    actor: string,
    competition: string,
    season: string,
  ): Promise<unknown> {
    return this.upstream.explorer({
      path: 'review/replay',
      method: 'POST',
      body: { competition, season },
      actor,
    });
  }

  // -- jobs -------------------------------------------------------------- //

  /**
   * Everything the jobs screen needs, resolved together.
   *
   * `active` is a filtered view of the same underlying file as `all`,
   * so fetching both is cheap and keeps the screen internally
   * consistent — two separate browser calls could straddle a write and
   * show an active job that the list below claims is finished.
   */
  async jobsOverview(historyLimit = 100): Promise<Record<string, unknown>> {
    const [active, history] = await Promise.all([
      this.upstream.explorer({ path: 'jobs/active' }),
      this.upstream.explorer({ path: `jobs/history?limit=${historyLimit}` }),
    ]);
    return { active, history };
  }

  async job(jobId: string): Promise<unknown> {
    return this.upstream.explorer({
      path: `jobs/${encodeURIComponent(jobId)}`,
    });
  }

  /**
   * Start or restart collection for ONE (competition, season) task.
   *
   * Kept separate from `schedulerAction` because the Explorer's five
   * job endpoints are not five variants of one thing: start/restart are
   * scoped to a task, while pause/resume/cancel take no body and act on
   * the WHOLE scheduler. Collapsing them into one method is how a
   * "cancel" button ends up rendered next to a single job row while
   * actually cancelling every job — the distinction has to survive into
   * the UI, so it is enforced by the type here.
   */
  async taskAction(
    actor: string,
    action: 'start' | 'restart',
    competition: string,
    season: string,
  ): Promise<unknown> {
    return this.upstream.explorer({
      path: `jobs/${action}`,
      method: 'POST',
      body: { competition, season },
      actor,
    });
  }

  /** Pause / resume / cancel the scheduler as a whole. */
  async schedulerAction(
    actor: string,
    action: 'pause' | 'resume' | 'cancel',
  ): Promise<unknown> {
    this.logger.log(`scheduler ${action} by ${actor}`);
    return this.upstream.explorer({
      path: `jobs/${action}`,
      method: 'POST',
      body: {},
      actor,
    });
  }

  // -- quality ----------------------------------------------------------- //

  async qualityOverview(): Promise<Record<string, unknown>> {
    const [summary, datasets, entityResolution, duplicates] = await Promise.all([
      this.upstream.explorer({ path: 'quality' }),
      this.upstream.explorer({ path: 'quality/datasets' }),
      this.upstream.explorer({ path: 'entity-resolution' }),
      this.upstream.explorer({ path: 'duplicates' }),
    ]);
    return { summary, datasets, entityResolution, duplicates };
  }

  // -- runtime ----------------------------------------------------------- //

  /**
   * `/runtime` already aggregates status + scheduler + sources + qwen +
   * storage + config server-side, so it is passed through rather than
   * recomposed here. Recomposing would mean four extra round-trips for
   * a payload Explorer already assembles in one read.
   */
  async runtime(): Promise<unknown> {
    return this.upstream.explorer({ path: 'runtime' });
  }

  async reloadRuntime(actor: string): Promise<unknown> {
    this.logger.log(`runtime config reload by ${actor}`);
    return this.upstream.explorer({
      path: 'runtime/reload',
      method: 'POST',
      body: {},
      actor,
    });
  }
}
