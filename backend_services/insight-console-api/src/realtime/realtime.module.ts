import { Module } from '@nestjs/common';

import { UpstreamModule } from '../upstream/upstream.module';
import { RealtimeController } from './realtime.controller';
import { RealtimeService } from './realtime.service';

@Module({
  imports: [UpstreamModule],
  controllers: [RealtimeController],
  providers: [RealtimeService],
  exports: [RealtimeService],
})
export class RealtimeModule {}
