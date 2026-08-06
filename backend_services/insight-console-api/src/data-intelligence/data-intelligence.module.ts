import { Module } from '@nestjs/common';

import { UpstreamModule } from '../upstream/upstream.module';
import { DataIntelligenceController } from './data-intelligence.controller';

@Module({
  imports: [UpstreamModule],
  controllers: [DataIntelligenceController],
})
export class DataIntelligenceModule {}
