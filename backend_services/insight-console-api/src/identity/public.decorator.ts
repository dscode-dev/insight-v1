import { SetMetadata } from '@nestjs/common';

/** Opts a route out of the global IdentityGuard. Use sparingly. */
export const IS_PUBLIC_KEY = 'consoleApiPublic';
export const Public = () => SetMetadata(IS_PUBLIC_KEY, true);
