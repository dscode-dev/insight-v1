import { Controller, Get } from '@nestjs/common';

import { Public } from '../identity/public.decorator';

/**
 * The ONLY unauthenticated surface on this service.
 *
 * @Public is load-bearing: IdentityGuard is registered globally, so
 * without it the container healthcheck gets a 401, never reports
 * healthy, and `insight-console` — which declares
 * `depends_on: {condition: service_healthy}` — never starts either.
 */
@Controller('health')
export class HealthController {
  @Public()
  @Get()
  health(): { status: string; service: string } {
    return { status: 'ok', service: 'insight-console-api' };
  }
}
