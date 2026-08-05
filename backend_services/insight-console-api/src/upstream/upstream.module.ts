import { Module } from '@nestjs/common';

import { UpstreamService } from './upstream.service';

@Module({
  providers: [
    // useFactory, NOT the class token: the constructor takes an
    // injectable-looking `fetcher` parameter that only exists as a test
    // seam. Letting Nest resolve it fails at BOOT with
    // "Nest can't resolve dependencies of UpstreamService" — a failure
    // neither typecheck nor unit tests catch, since both construct the
    // service directly.
    { provide: UpstreamService, useFactory: () => new UpstreamService() },
  ],
  exports: [UpstreamService],
})
export class UpstreamModule {}
