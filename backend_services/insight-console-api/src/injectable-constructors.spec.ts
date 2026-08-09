import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

/**
 * No @Injectable may take an optional or defaulted constructor parameter.
 *
 * Nest resolves EVERY constructor parameter of a provider, including
 * ones written as `param?: T` or `param: T = fallback`. Those read like
 * "Nest will skip this, it is only a test seam" and they are not: the
 * container looks for a provider of that type, fails, and the process
 * dies at BOOT.
 *
 * Neither typecheck nor unit tests catch it, because both construct the
 * class directly and never go through the container. This has now bitten
 * three times in this service — UpstreamService (`fetcher`),
 * SessionCacheService (`now`) and DatabaseService (`connectionString`) —
 * each time discovered only by running the container.
 *
 * The two legitimate shapes:
 *   - no such parameter at all (DatabaseService now), or
 *   - a `useFactory` provider that constructs it explicitly, in which
 *     case the class is not resolved by the container and is exempt.
 */

const SRC = __dirname;

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...sourceFiles(full));
    } else if (entry.endsWith('.ts') && !entry.endsWith('.spec.ts')) {
      out.push(full);
    }
  }
  return out;
}

/** Classes the modules construct themselves via useFactory. */
function factoryProvided(): Set<string> {
  const names = new Set<string>();
  for (const file of sourceFiles(SRC)) {
    if (!file.endsWith('.module.ts')) continue;
    const source = readFileSync(file, 'utf8');
    for (const match of source.matchAll(
      /provide:\s*(\w+)\s*,\s*useFactory/g,
    )) {
      names.add(match[1]!);
    }
  }
  return names;
}

interface Offender {
  readonly file: string;
  readonly cls: string;
  readonly params: string;
}

function findOffenders(): Offender[] {
  const exempt = factoryProvided();
  const offenders: Offender[] = [];

  for (const file of sourceFiles(SRC)) {
    const source = readFileSync(file, 'utf8');
    if (!source.includes('@Injectable')) continue;

    // Class declarations that carry the decorator, with their
    // constructor parameter list.
    for (const match of source.matchAll(
      /@Injectable\(\)[\s\S]{0,400}?export class (\w+)[\s\S]*?constructor\s*\(([\s\S]*?)\)\s*\{/g,
    )) {
      const cls = match[1]!;
      const params = match[2]!;
      if (exempt.has(cls)) continue;

      // `?:` marks optional; `=` at parameter depth marks a default.
      const optional = /\w\??\s*\?\s*:/.test(params) || /\w\s*\?\s*:/.test(params);
      const defaulted = /[^=!<>]=[^=>]/.test(params);
      if (optional || defaulted) {
        offenders.push({
          file: file.slice(SRC.length + 1),
          cls,
          params: params.replace(/\s+/g, ' ').trim(),
        });
      }
    }
  }
  return offenders;
}

describe('@Injectable constructors', () => {
  it('finds the injectables it is supposed to be checking', () => {
    // A scanner that matched nothing would make the assertion below
    // vacuously true.
    const files = sourceFiles(SRC).filter((f) =>
      readFileSync(f, 'utf8').includes('@Injectable'),
    );
    expect(files.length).toBeGreaterThanOrEqual(4);
  });

  it('none takes an optional or defaulted parameter', () => {
    const offenders = findOffenders();
    const detail = offenders
      .map((o) => `${o.file}: ${o.cls}(${o.params})`)
      .join('\n  ');
    expect(
      offenders,
      // Jest ignores this second argument, but it documents the fix for
      // whoever reads the failure.
    ).toEqual([]);
    expect(detail).toBe('');
  });
});
