import { Module } from '@nestjs/common';

import { UpstreamModule } from '../upstream/upstream.module';
import { ExplorerOpsController } from './explorer-ops.controller';
import { ExplorerOpsService } from './explorer-ops.service';

@Module({
  imports: [UpstreamModule],
  controllers: [ExplorerOpsController],
  providers: [ExplorerOpsService],
  exports: [ExplorerOpsService],
})
export class ExplorerOpsModule {}
