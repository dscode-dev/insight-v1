import { Injectable, Logger, OnModuleDestroy } from '@nestjs/common';
import { Pool, QueryResultRow } from 'pg';

import { getConfig } from '../config/config';

/**
 * Postgres access for the Control Plane's own data.
 *
 * The Control Plane is authority over administrative identity —
 * operators, sessions, RBAC, the audit spine — so it owns a schema and
 * talks to it directly. It never reads another domain's tables: Atlas
 * and Explorer stay authority over theirs and are reached over their
 * APIs, which is the same rule that keeps this service out of Atlas's
 * `atlas` schema even though both live in one database.
 */
@Injectable()
export class DatabaseService implements OnModuleDestroy {
  private readonly logger = new Logger(DatabaseService.name);
  private readonly pool: Pool;

  // NO constructor parameters. An optional or defaulted parameter on an
  // @Injectable is one Nest still tries to resolve — `connectionString?:
  // string` made it look for a `String` provider and killed the process
  // at BOOT, which neither typecheck nor unit tests catch because both
  // construct the class directly. Third time this trap fired in this
  // service (UpstreamService, SessionCacheService, here), so the
  // parameter is gone rather than worked around.
  constructor() {
    const config = getConfig();
    this.pool = new Pool({
      connectionString: config.CONTROL_PLANE_DATABASE_URL,
      max: config.DATABASE_POOL_SIZE,
      // A hung connection must not hold a request forever: every caller
      // here is on a request path an operator is waiting on.
      connectionTimeoutMillis: 5_000,
      idleTimeoutMillis: 30_000,
      // Search path is set explicitly rather than baked into queries so
      // a table moved between schemas does not silently resolve to a
      // same-named table in `public`.
      options: '-c search_path=control_plane,public',
    });
    this.pool.on('error', (error) => {
      // An idle-client error is emitted on the pool, not on a query, so
      // without this the process would die on a Postgres restart.
      this.logger.error(`idle client error: ${error.message}`);
    });
  }

  async query<T extends QueryResultRow = QueryResultRow>(
    sql: string,
    params: unknown[] = [],
  ): Promise<T[]> {
    const result = await this.pool.query<T>(sql, params);
    return result.rows;
  }

  async queryOne<T extends QueryResultRow = QueryResultRow>(
    sql: string,
    params: unknown[] = [],
  ): Promise<T | null> {
    const rows = await this.query<T>(sql, params);
    return rows[0] ?? null;
  }

  /** True when the database answers. Used by /health/ready. */
  async healthy(): Promise<boolean> {
    try {
      await this.pool.query('SELECT 1');
      return true;
    } catch (error) {
      this.logger.warn(
        `database unreachable: ${error instanceof Error ? error.message : 'unknown'}`,
      );
      return false;
    }
  }

  async onModuleDestroy(): Promise<void> {
    await this.pool.end();
  }
}
