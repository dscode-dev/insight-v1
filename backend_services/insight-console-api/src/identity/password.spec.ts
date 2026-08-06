import {
  PASSWORD_MIN_LENGTH,
  WeakPasswordError,
  assertUsablePassword,
  hashPassword,
  verifyPassword,
} from './password';

// scrypt at N=32768 is intentionally slow; these run a handful of hashes.
jest.setTimeout(30_000);

describe('password hashing', () => {
  it('round-trips a password', async () => {
    const hash = await hashPassword('a-long-enough-password');
    expect(await verifyPassword('a-long-enough-password', hash)).toBe(true);
  });

  it('rejects the wrong password', async () => {
    const hash = await hashPassword('a-long-enough-password');
    expect(await verifyPassword('a-long-enough-passwerd', hash)).toBe(false);
  });

  it('produces a different hash every time', async () => {
    const [first, second] = await Promise.all([
      hashPassword('a-long-enough-password'),
      hashPassword('a-long-enough-password'),
    ]);
    // Random salt: identical passwords must not produce identical
    // digests, or the table leaks which operators share a password.
    expect(first).not.toEqual(second);
    expect(await verifyPassword('a-long-enough-password', second)).toBe(true);
  });

  it('carries its own cost parameters', async () => {
    const hash = await hashPassword('a-long-enough-password');
    const [scheme, n, r, p] = hash.split('$');
    // Self-describing so raising the cost later does not invalidate
    // every existing password.
    expect(scheme).toBe('scrypt');
    expect(Number(n)).toBeGreaterThanOrEqual(16384);
    expect(Number(r)).toBeGreaterThan(0);
    expect(Number(p)).toBeGreaterThan(0);
  });

  it('never stores the password itself', async () => {
    const hash = await hashPassword('correct-horse-battery');
    expect(hash).not.toContain('correct-horse-battery');
  });

  it.each([
    ['', 'empty'],
    ['not-a-hash', 'no separators'],
    ['bcrypt$1$2$3$4$5', 'wrong scheme'],
    ['scrypt$x$8$1$c2FsdA==$aGFzaA==', 'non-numeric cost'],
    ['scrypt$32768$8$1$$', 'empty salt and hash'],
    ['scrypt$32768$8$1$c2FsdA==', 'truncated'],
  ])('returns false for a malformed hash (%s)', async (stored) => {
    // A corrupt stored hash must read as "wrong password", never throw:
    // a 500 here would tell an attacker the account exists.
    await expect(verifyPassword('anything', stored)).resolves.toBe(false);
  });
});

describe('assertUsablePassword', () => {
  it('accepts a long enough password', () => {
    expect(() => assertUsablePassword('a'.repeat(PASSWORD_MIN_LENGTH))).not.toThrow();
  });

  it('rejects a short password', () => {
    expect(() => assertUsablePassword('a'.repeat(PASSWORD_MIN_LENGTH - 1))).toThrow(
      WeakPasswordError,
    );
  });

  it('counts code points, not bytes', () => {
    // A 12-character passphrase of non-Latin characters is not weaker
    // for being more bytes.
    expect(() => assertUsablePassword('senhaçãoçãoç')).not.toThrow();
  });

  it('refuses the __required__ placeholder', () => {
    // This repo's .env template ships it for unfilled secrets, and it
    // has reached a running deployment before — it became the Postgres
    // superuser name on the robozao host.
    expect(() => assertUsablePassword('__required__')).toThrow(WeakPasswordError);
  });
});
