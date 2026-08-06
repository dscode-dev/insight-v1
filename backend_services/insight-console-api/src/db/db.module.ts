import { Global, Module } from '@nestjs/common';

import { DatabaseService } from './database.service';

/**
 * Global: the Control Plane's own schema is reached from identity, the
 * audit spine and the health probe alike, and threading a DatabaseModule
 * import through each of them adds nothing.
 */
@Global()
@Module({
  providers: [DatabaseService],
  exports: [DatabaseService],
})
export class DbModule {}
