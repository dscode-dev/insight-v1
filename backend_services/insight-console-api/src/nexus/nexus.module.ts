import { Module } from '@nestjs/common';

import { UpstreamModule } from '../upstream/upstream.module';
import { NexusController } from './nexus.controller';

@Module({
  imports: [UpstreamModule],
  controllers: [NexusController],
})
export class NexusModule {}
