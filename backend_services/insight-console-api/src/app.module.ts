import { Module } from '@nestjs/common';
import { APP_GUARD } from '@nestjs/core';

import { DataIntelligenceModule } from './data-intelligence/data-intelligence.module';
import { NexusModule } from './nexus/nexus.module';
import { DbModule } from './db/db.module';
import { ExplorerOpsModule } from './explorer-ops/explorer-ops.module';
import { HealthController } from './health/health.controller';
import { IdentityGuard } from './identity/identity.guard';
import { IdentityModule } from './identity/identity.module';
import { PlatformModule } from './platform/platform.module';
import { ProductPlaneModule } from './product-plane/product-plane.module';
import { QualityGateModule } from './quality-gate/quality-gate.module';
import { RealtimeModule } from './realtime/realtime.module';
import { UpstreamModule } from './upstream/upstream.module';

/**
 * Insight Control Plane.
 *
 * Per insight-context.md v2.0 this service is the administrative
 * authority for the Intelligence plane: it authenticates operators,
 * owns their sessions and RBAC, carries the audit spine, and is the
 * ONLY thing the console talks to — every other internal service is
 * reached through here, never directly from the browser or the Next
 * server.
 */
@Module({
  imports: [
    DbModule,
    DataIntelligenceModule,
    NexusModule,
    IdentityModule,
    ExplorerOpsModule,
    PlatformModule,
    ProductPlaneModule,
    QualityGateModule,
    RealtimeModule,
    UpstreamModule,
  ],
  controllers: [HealthController],
  providers: [
    // Fail-closed: every route requires a live operator session unless
    // it explicitly opts out with @Public.
    { provide: APP_GUARD, useClass: IdentityGuard },
  ],
})
export class AppModule {}
