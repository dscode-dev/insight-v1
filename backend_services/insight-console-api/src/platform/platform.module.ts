import { Module } from '@nestjs/common';

import { NodeAgentController } from './node-agent.controller';
import { NodeAgentService } from './node-agent.service';
import { PlatformController } from './platform.controller';
import { PlatformService } from './platform.service';

@Module({
  controllers: [PlatformController, NodeAgentController],
  providers: [PlatformService, NodeAgentService],
  exports: [PlatformService, NodeAgentService],
})
export class PlatformModule {}
