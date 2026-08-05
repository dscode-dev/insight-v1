import {
  IDENTITY_MAX_AGE_SECONDS,
  IdentityVerificationError,
  OperatorIdentity,
  signIdentity,
  verifyIdentity,
} from './operator-identity';

const SECRET = 'a'.repeat(48);
const OTHER_SECRET = 'b'.repeat(48);
const NOW = 1_800_000_000;

function identity(overrides: Partial<OperatorIdentity> = {}): OperatorIdentity {
  return {
    operatorId: 'op-1',
    operatorUsername: 'ana',
    identityId: 'op-1',
    identityKind: 'operator',
    permissions: ['console.access', 'config.write'],
    role: 'SuperAdmin',
    sessionId: 'c'.repeat(64),
    correlationId: 'corr-1',
    issuedAt: NOW,
    ...overrides,
  };
}

describe('operator identity envelope', () => {
  it('round-trips a signed identity', () => {
    const { envelope, signature } = signIdentity(identity(), SECRET);
    const verified = verifyIdentity(envelope, signature, SECRET, NOW);

    expect(verified.operatorId).toBe('op-1');
    expect(verified.identityKind).toBe('operator');
    expect(verified.permissions).toEqual(['console.access', 'config.write']);
    expect(verified.sessionId).toBe('c'.repeat(64));
  });

  it('rejects a payload signed with a different secret', () => {
    const { envelope, signature } = signIdentity(identity(), OTHER_SECRET);
    expect(() => verifyIdentity(envelope, signature, SECRET, NOW)).toThrow(
      IdentityVerificationError,
    );
  });

  it('rejects a tampered envelope', () => {
    const { signature } = signIdentity(identity(), SECRET);
    const tampered = Buffer.from(
      JSON.stringify({ ...identity(), operatorId: 'op-999' }),
      'utf8',
    ).toString('base64url');

    // This is the attack the signature exists to stop: swapping the
    // identity while keeping a signature that was valid for another one.
    expect(() => verifyIdentity(tampered, signature, SECRET, NOW)).toThrow(
      /signature mismatch/,
    );
  });

  it('rejects a missing envelope or signature', () => {
    const { envelope, signature } = signIdentity(identity(), SECRET);
    expect(() => verifyIdentity(undefined, signature, SECRET, NOW)).toThrow(
      /missing/,
    );
    expect(() => verifyIdentity(envelope, undefined, SECRET, NOW)).toThrow(
      /missing/,
    );
  });

  it('rejects a malformed signature without throwing a RangeError', () => {
    const { envelope } = signIdentity(identity(), SECRET);
    // timingSafeEqual throws RangeError on length mismatch — the code
    // must length-check first and produce a clean domain error.
    expect(() => verifyIdentity(envelope, 'short', SECRET, NOW)).toThrow(
      IdentityVerificationError,
    );
  });

  it('rejects a replayed envelope past the freshness window', () => {
    const { envelope, signature } = signIdentity(identity(), SECRET);
    const later = NOW + IDENTITY_MAX_AGE_SECONDS + 1;
    expect(() => verifyIdentity(envelope, signature, SECRET, later)).toThrow(
      /expired/,
    );
  });

  it('accepts an envelope inside the freshness window', () => {
    const { envelope, signature } = signIdentity(identity(), SECRET);
    const later = NOW + IDENTITY_MAX_AGE_SECONDS - 1;
    expect(verifyIdentity(envelope, signature, SECRET, later).operatorId).toBe(
      'op-1',
    );
  });

  it('rejects an envelope dated far in the future', () => {
    const { envelope, signature } = signIdentity(
      identity({ issuedAt: NOW + 600 }),
      SECRET,
    );
    expect(() => verifyIdentity(envelope, signature, SECRET, NOW)).toThrow(
      /future/,
    );
  });

  it('rejects an envelope missing required identity fields', () => {
    for (const missing of ['operatorId', 'identityId', 'sessionId', 'issuedAt']) {
      const partial: Record<string, unknown> = { ...identity() };
      delete partial[missing];
      const envelope = Buffer.from(JSON.stringify(partial), 'utf8').toString(
        'base64url',
      );
      const { signature } = signIdentityRaw(envelope, SECRET);
      expect(() => verifyIdentity(envelope, signature, SECRET, NOW)).toThrow(
        new RegExp(missing),
      );
    }
  });

  it('rejects a non-JSON envelope', () => {
    const envelope = Buffer.from('not json', 'utf8').toString('base64url');
    const { signature } = signIdentityRaw(envelope, SECRET);
    expect(() => verifyIdentity(envelope, signature, SECRET, NOW)).toThrow(
      /not valid JSON/,
    );
  });

  it('falls back to "operator" for an unrecognised identityKind', () => {
    const raw = { ...identity(), identityKind: 'attacker-supplied' };
    const envelope = Buffer.from(JSON.stringify(raw), 'utf8').toString('base64url');
    const { signature } = signIdentityRaw(envelope, SECRET);
    expect(verifyIdentity(envelope, signature, SECRET, NOW).identityKind).toBe(
      'operator',
    );
  });

  it('never carries the session token itself', () => {
    const { envelope } = signIdentity(identity(), SECRET);
    const decoded = Buffer.from(envelope, 'base64url').toString('utf8');
    expect(decoded).not.toMatch(/token/i);
  });
});

/** Sign an already-encoded envelope (for negative-path fixtures). */
function signIdentityRaw(envelope: string, secret: string): { signature: string } {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { createHmac } = require('node:crypto');
  return {
    signature: createHmac('sha256', secret).update(envelope).digest('hex'),
  };
}
