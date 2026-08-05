import { Body, Controller, HttpCode, Post, UnauthorizedException } from '@nestjs/common';

import { Public } from '../identity/public.decorator';
import { SessionCacheService } from './session-cache.service';

interface ResolveBody {
  readonly token?: string;
}

/**
 * Session resolution for the Next.js BFF.
 *
 * Deliberately @Public: this is the ONE endpoint that cannot require a
 * signed identity envelope, because it is what the BFF calls in order to
 * LEARN the identity in the first place. The session token itself is the
 * credential here, and it is verified against the Gateway — this service
 * never decides on its own whether a token is valid.
 */
@Controller('internal/session')
export class AuthController {
  constructor(private readonly sessions: SessionCacheService) {}

  @Public()
  @Post('resolve')
  @HttpCode(200)
  async resolve(@Body() body: ResolveBody) {
    const session = await this.sessions.resolve(body?.token ?? '');
    if (session === null) {
      throw new UnauthorizedException('session_unresolved');
    }
    return session;
  }

  @Public()
  @Post('invalidate')
  @HttpCode(204)
  invalidate(@Body() body: ResolveBody): void {
    this.sessions.invalidate(body?.token ?? '');
  }
}
