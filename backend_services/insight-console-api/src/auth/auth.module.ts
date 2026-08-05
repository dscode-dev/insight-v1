import { Module } from '@nestjs/common';

import { AuthController } from './auth.controller';
import { SessionCacheService } from './session-cache.service';

@Module({
  controllers: [AuthController],
  providers: [
    // Default construction uses global fetch + Date.now; the spec
    // injects fakes directly.
    { provide: SessionCacheService, useFactory: () => new SessionCacheService() },
  ],
  exports: [SessionCacheService],
})
export class AuthModule {}
