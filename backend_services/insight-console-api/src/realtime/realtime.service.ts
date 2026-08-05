import { Injectable, Logger, OnModuleDestroy } from '@nestjs/common';

import { getConfig } from '../config/config';
import { UpstreamService } from '../upstream/upstream.service';
import { Channel, ChannelRegistry } from './channel-registry';

/**
 * Declares the console's realtime channels and owns their lifecycle.
 *
 * Each channel replaces a client-side polling loop. The names map 1:1
 * onto the worst offenders found in the console audit so the migration
 * is auditable screen by screen.
 */
@Injectable()
export class RealtimeService implements OnModuleDestroy {
  private readonly logger = new Logger(RealtimeService.name);
  private readonly registry: ChannelRegistry;

  constructor(private readonly upstream: UpstreamService) {
    this.registry = new ChannelRegistry(getConfig().REALTIME_POLL_INTERVAL_MS);
    this.declareChannels();
  }

  channels(): string[] {
    return this.registry.names();
  }

  channel(name: string): Channel | undefined {
    return this.registry.get(name);
  }

  onModuleDestroy(): void {
    this.registry.stopAll();
  }

  private declareChannels(): void {
    // Replaces data-intelligence-center's 7s dashboard poll (4 screens
    // were calling this path against a 404 until it was added).
    this.registry.register({
      name: 'explorer.dashboard',
      poll: async () => ({
        dashboard: await this.upstream.explorer({
          path: 'data-intelligence/dashboard',
        }),
      }),
    });

    // Replaces execution-detail's 3-endpoint 7s poll.
    this.registry.register({
      name: 'explorer.executions',
      poll: async () => ({
        executions: await this.upstream.explorer({ path: 'executions' }),
      }),
    });

    this.registry.register({
      name: 'explorer.tickets',
      poll: async () => ({
        tickets: await this.upstream.explorer({ path: 'tickets?status=open' }),
      }),
    });

    // A Quality Gate replay runs for minutes; the screen needs its
    // status without a per-execution poll. The LIST carries every
    // running execution's status, so one channel serves both the
    // overview and whichever replay an operator is watching — no
    // per-execution channel, and no fan-out that grows with history.
    this.registry.register({
      name: 'atlas.backtests',
      poll: async () => ({
        backtests: await this.upstream.atlas({ path: 'backtests?limit=50' }),
      }),
    });

    this.logger.log(`realtime channels declared: ${this.channels().join(', ')}`);
  }
}
