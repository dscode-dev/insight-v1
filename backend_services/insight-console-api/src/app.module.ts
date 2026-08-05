import { Module } from '@nestjs/common';
import { APP_GUARD } from '@nestjs/core';

import { AuthModule } from './auth/auth.module';
import { ExplorerOpsModule } from './explorer-ops/explorer-ops.module';
import { HealthController } from './health/health.controller';
import { IdentityGuard } from './identity/identity.guard';
import { QualityGateModule } from './quality-gate/quality-gate.module';
import { RealtimeModule } from './realtime/realtime.module';
import { UpstreamModule } from './upstream/upstream.module';

@Module({
  imports: [
    AuthModule,
    ExplorerOpsModule,
    QualityGateModule,
    RealtimeModule,
    UpstreamModule,
  ],
  controllers: [HealthController],
  providers: [
    // Fail-closed by default: every route requires a console-signed
    // identity envelope unless it explicitly opts out with @Public.
    { provide: APP_GUARD, useClass: IdentityGuard },
  ],
})
export class AppModule {}
