import { Reflector } from '@nestjs/core';

import { IS_PUBLIC_KEY } from '../identity/public.decorator';
import { HealthController } from './health.controller';

describe('HealthController', () => {
  it('reports ok', () => {
    expect(new HealthController().health()).toEqual({
      status: 'ok',
      service: 'insight-console-api',
    });
  });

  it('is marked @Public so the container healthcheck can reach it', () => {
    // Regression: IdentityGuard is global, so without @Public the probe
    // gets a 401, the container never reports healthy, and
    // insight-console (depends_on: service_healthy) never starts.
    // Caught only by actually running the container — pinned here.
    const isPublic = new Reflector().get<boolean>(
      IS_PUBLIC_KEY,
      HealthController.prototype.health,
    );
    expect(isPublic).toBe(true);
  });
});
