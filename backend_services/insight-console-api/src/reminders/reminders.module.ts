import { Module } from '@nestjs/common';

import { RemindersController } from './reminders.controller';
import { RemindersService } from './reminders.service';

/**
 * Operational deadlines. Reads DbModule (global), talks to nothing
 * upstream: the reminders are the Control Plane's own state.
 */
@Module({
  controllers: [RemindersController],
  providers: [RemindersService],
  exports: [RemindersService],
})
export class RemindersModule {}
