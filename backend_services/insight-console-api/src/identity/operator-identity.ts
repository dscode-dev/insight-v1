/**
 * The identity envelope the Next.js BFF signs and this service verifies.
 *
 * WHY A SIGNED ENVELOPE INSTEAD OF A PLAIN HEADER
 * The console's whole security posture rests on one rule: operator
 * identity is derived SERVER-SIDE and is never something a caller can
 * assert (`assertNoClientActor` in
 * `lib/control-plane/security/operator-context.ts`). Introducing a second
 * process would break that rule if it simply trusted an `X-Operator`
 * header — anyone able to reach this port could then claim to be any
 * operator. The envelope is HMAC-signed with a secret only the two
 * server processes hold, so this service can verify that the identity
 * really came from the console's own server side.
 *
 * The Gateway remains the sole owner of identity. This carries an
 * already-resolved identity between two console processes; it never
 * mints one.
 */
import { createHmac, timingSafeEqual } from 'node:crypto';

/** Header carrying the base64url JSON envelope. */
export const IDENTITY_HEADER = 'x-console-identity';
/** Header carrying the hex HMAC-SHA256 of the envelope. */
export const IDENTITY_SIGNATURE_HEADER = 'x-console-identity-signature';

/**
 * Envelope freshness window. A captured envelope replayed after this is
 * rejected — bounded blast radius if one ever leaks into a log.
 */
export const IDENTITY_MAX_AGE_SECONDS = 60;

export interface OperatorIdentity {
  readonly operatorId: string;
  readonly operatorUsername: string | null;
  /** Effective operational identity (differs from operatorId only under delegation). */
  readonly identityId: string;
  readonly identityKind: 'operator' | 'official_identity' | 'agent';
  readonly permissions: readonly string[];
  readonly role: string;
  /** sha256 of the session token — a stable key, never the credential. */
  readonly sessionId: string;
  readonly correlationId: string | null;
  /** Unix seconds when the envelope was signed. */
  readonly issuedAt: number;
}

export class IdentityVerificationError extends Error {}

export function signIdentity(identity: OperatorIdentity, secret: string): {
  envelope: string;
  signature: string;
} {
  const envelope = Buffer.from(JSON.stringify(identity), 'utf8').toString('base64url');
  return { envelope, signature: hmac(envelope, secret) };
}

export function verifyIdentity(
  envelope: string | undefined,
  signature: string | undefined,
  secret: string,
  nowSeconds: number = Math.floor(Date.now() / 1000),
): OperatorIdentity {
  if (!envelope || !signature) {
    throw new IdentityVerificationError('identity envelope or signature missing');
  }

  const expected = hmac(envelope, secret);
  // Constant-time compare. `timingSafeEqual` throws on length mismatch,
  // so the lengths are checked first — both signatures are fixed-length
  // hex here, but a malformed header must produce a clean rejection
  // rather than an unhandled RangeError.
  const provided = Buffer.from(signature, 'utf8');
  const expectedBuffer = Buffer.from(expected, 'utf8');
  if (
    provided.length !== expectedBuffer.length ||
    !timingSafeEqual(provided, expectedBuffer)
  ) {
    throw new IdentityVerificationError('identity signature mismatch');
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(Buffer.from(envelope, 'base64url').toString('utf8'));
  } catch {
    throw new IdentityVerificationError('identity envelope is not valid JSON');
  }

  const identity = asIdentity(parsed);

  const age = nowSeconds - identity.issuedAt;
  if (age > IDENTITY_MAX_AGE_SECONDS) {
    throw new IdentityVerificationError(`identity envelope expired (${age}s old)`);
  }
  // A future-dated envelope means clock skew or tampering; allow a small
  // tolerance and reject beyond it rather than trusting it indefinitely.
  if (age < -IDENTITY_MAX_AGE_SECONDS) {
    throw new IdentityVerificationError('identity envelope is dated in the future');
  }

  return identity;
}

function asIdentity(value: unknown): OperatorIdentity {
  if (typeof value !== 'object' || value === null) {
    throw new IdentityVerificationError('identity envelope is not an object');
  }
  const raw = value as Record<string, unknown>;
  const operatorId = raw.operatorId;
  const identityId = raw.identityId;
  const issuedAt = raw.issuedAt;
  const sessionId = raw.sessionId;

  if (typeof operatorId !== 'string' || operatorId.length === 0) {
    throw new IdentityVerificationError('identity envelope missing operatorId');
  }
  if (typeof identityId !== 'string' || identityId.length === 0) {
    throw new IdentityVerificationError('identity envelope missing identityId');
  }
  if (typeof sessionId !== 'string' || sessionId.length === 0) {
    throw new IdentityVerificationError('identity envelope missing sessionId');
  }
  if (typeof issuedAt !== 'number' || !Number.isFinite(issuedAt)) {
    throw new IdentityVerificationError('identity envelope missing issuedAt');
  }

  const kind = raw.identityKind;
  const identityKind: OperatorIdentity['identityKind'] =
    kind === 'official_identity' || kind === 'agent' ? kind : 'operator';

  return {
    operatorId,
    operatorUsername:
      typeof raw.operatorUsername === 'string' ? raw.operatorUsername : null,
    identityId,
    identityKind,
    permissions: Array.isArray(raw.permissions)
      ? raw.permissions.filter((item): item is string => typeof item === 'string')
      : [],
    role: typeof raw.role === 'string' ? raw.role : '',
    sessionId,
    correlationId:
      typeof raw.correlationId === 'string' ? raw.correlationId : null,
    issuedAt,
  };
}

function hmac(payload: string, secret: string): string {
  return createHmac('sha256', secret).update(payload).digest('hex');
}
