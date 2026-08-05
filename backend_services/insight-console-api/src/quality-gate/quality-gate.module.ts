import { Module } from '@nestjs/common';

import { UpstreamModule } from '../upstream/upstream.module';
import { QualityGateController } from './quality-gate.controller';
import { QualityGateService } from './quality-gate.service';

@Module({
  imports: [UpstreamModule],
  controllers: [QualityGateController],
  providers: [QualityGateService],
  exports: [QualityGateService],
})
export class QualityGateModule {}
