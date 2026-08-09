import { Global, Module } from '@nestjs/common';

import { SessionCacheService } from '../auth/session-cache.service';
import { OperatorAuthController } from './operator-auth.controller';
import { OperatorRepository } from './operator.repository';

/**
 * Administrative identity — the Control Plane's core responsibility per
 * insight-context.md v2.0.
 *
 * Global because IdentityGuard is registered as a global APP_GUARD and
 * needs SessionCacheService; without this every feature module would
 * have to import it just to be guarded.
 */
@Global()
@Module({
  controllers: [OperatorAuthController],
  providers: [
    OperatorRepository,
    {
      // useFactory, not the bare class: SessionCacheService takes a
      // `now` clock as a second constructor parameter that exists only
      // as a test seam. Nest would try to resolve it and fail at BOOT —
      // a failure neither typecheck nor unit tests catch, because both
      // construct it directly. Same trap UpstreamService hit.
      provide: SessionCacheService,
      useFactory: (operators: OperatorRepository) =>
        new SessionCacheService(operators),
      inject: [OperatorRepository],
    },
  ],
  exports: [OperatorRepository, SessionCacheService],
})
export class IdentityModule {}
