import { Controller, Get, Req } from '@nestjs/common';

import {
  IDENTITY_REQUEST_KEY,
  RequestWithIdentity,
} from '../identity/identity.guard';
import { NodeAgentService } from './node-agent.service';
import { PlatformHealth, PlatformService } from './platform.service';

@Controller('platform')
export class PlatformController {
  constructor(
    private readonly platform: PlatformService,
    private readonly nodeAgent: NodeAgentService,
  ) {}

  /**
   * One call replacing the console's four direct health probes.
   *
   * The Node Agent is folded in here rather than exposed separately:
   * the console's snapshot needs both together, and two round-trips for
   * one screen is what this migration is removing.
   */
  @Get('health')
  async health(
    @Req() request: RequestWithIdentity,
  ): Promise<PlatformHealth & { nodeAgent: unknown }> {
    const identity = request[IDENTITY_REQUEST_KEY];
    const [platform, nodeAgent] = await Promise.all([
      this.platform.health(),
      this.nodeAgent.status({
        id: identity?.operator.id,
        username: identity?.operator.username,
        role: identity?.operator.role,
      }),
    ]);
    return { ...platform, nodeAgent };
  }
}
