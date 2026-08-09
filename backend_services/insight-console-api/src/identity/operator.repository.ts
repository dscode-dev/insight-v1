import { createHash, randomBytes, randomUUID } from 'node:crypto';

import { Injectable, Logger } from '@nestjs/common';

import { DatabaseService } from '../db/database.service';
import { getConfig } from '../config/config';
import { hashPassword, verifyPassword } from './password';
import { normalizeRole, permissionsForRole, Role } from './rbac';

export interface OperatorRecord {
  readonly id: string;
  readonly username: string;
  readonly email: string;
  readonly displayName: string;
  readonly role: Role;
  readonly permissions: string[];
  readonly isActive: boolean;
}

export interface IssuedSession {
  readonly token: string;
  readonly sessionId: string;
  readonly expiresAt: Date;
  readonly operator: OperatorRecord;
}

export interface ResolvedSession {
  readonly operator: OperatorRecord;
  readonly sessionId: string;
  readonly expiresAt: Date;
}

interface OperatorRow {
  id: string;
  username: string;
  email: string;
  display_name: string;
  role: string;
  is_active: boolean;
  password_hash?: string;
}

/** Non-secret session key: sha256 of the opaque token. */
export function sessionKey(token: string): string {
  return createHash('sha256').update(token).digest('hex');
}

function toRecord(row: OperatorRow): OperatorRecord {
  const role = normalizeRole(row.role);
  return {
    id: row.id,
    username: row.username,
    email: row.email,
    displayName: row.display_name || row.username,
    role,
    permissions: permissionsForRole(role),
    isActive: row.is_active,
  };
}

@Injectable()
export class OperatorRepository {
  private readonly logger = new Logger(OperatorRepository.name);

  constructor(private readonly db: DatabaseService) {}

  /**
   * Verify credentials. Returns null for every failure mode — wrong
   * password, unknown identifier, deactivated account.
   *
   * The caller cannot tell them apart on purpose: distinguishing them
   * turns the login form into an account-enumeration oracle.
   */
  async authenticate(
    identifier: string,
    password: string,
  ): Promise<OperatorRecord | null> {
    const row = await this.db.queryOne<OperatorRow>(
      `SELECT id::text, username, email, display_name, role, is_active, password_hash
         FROM control_plane.operators
        WHERE username = $1 OR lower(email) = lower($1)`,
      [identifier],
    );

    if (row === null || !row.password_hash) {
      // Hash anyway, against a dummy digest, so a missing account does
      // not return measurably faster than a wrong password.
      await verifyPassword(password, DUMMY_HASH);
      return null;
    }
    const ok = await verifyPassword(password, row.password_hash);
    if (!ok) {
      return null;
    }
    if (!row.is_active) {
      // Checked AFTER the password so a deactivated account is not
      // distinguishable from a wrong one by timing either.
      this.logger.warn(`login refused: operator ${row.username} is inactive`);
      return null;
    }
    return toRecord(row);
  }

  /** Issue an opaque session token. The token is returned once, never stored. */
  async issueSession(
    operator: OperatorRecord,
    meta: { userAgent?: string | null; ip?: string | null } = {},
  ): Promise<IssuedSession> {
    const token = randomBytes(32).toString('base64url');
    const hash = sessionKey(token);
    const expiresAt = new Date(
      Date.now() + getConfig().SESSION_TTL_HOURS * 3_600_000,
    );

    await this.db.query(
      `INSERT INTO control_plane.operator_sessions
         (id, operator_id, token_hash, expires_at, user_agent, ip_address)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [
        randomUUID(),
        operator.id,
        hash,
        expiresAt,
        meta.userAgent ?? null,
        meta.ip ?? null,
      ],
    );
    await this.db.query(
      'UPDATE control_plane.operators SET last_login_at = now() WHERE id = $1',
      [operator.id],
    );
    return { token, sessionId: hash, expiresAt, operator };
  }

  /**
   * Resolve a live session.
   *
   * Every condition is in the WHERE clause rather than checked in code:
   * expiry, revocation and the operator's active flag all have to hold
   * at query time, so deactivating an operator ends their sessions
   * immediately instead of at the next cache expiry.
   */
  async resolveSession(token: string): Promise<ResolvedSession | null> {
    if (!token) {
      return null;
    }
    const row = await this.db.queryOne<OperatorRow & { expires_at: Date }>(
      `SELECT o.id::text, o.username, o.email, o.display_name, o.role,
              o.is_active, s.expires_at
         FROM control_plane.operator_sessions s
         JOIN control_plane.operators o ON o.id = s.operator_id
        WHERE s.token_hash = $1
          AND s.revoked_at IS NULL
          AND s.expires_at > now()
          AND o.is_active = TRUE`,
      [sessionKey(token)],
    );
    if (row === null) {
      return null;
    }
    return {
      operator: toRecord(row),
      sessionId: sessionKey(token),
      expiresAt: row.expires_at,
    };
  }

  /** Best-effort last-seen bookkeeping. Never fails a request. */
  async touchSession(token: string): Promise<void> {
    try {
      await this.db.query(
        `UPDATE control_plane.operator_sessions
            SET last_seen_at = now()
          WHERE token_hash = $1 AND revoked_at IS NULL`,
        [sessionKey(token)],
      );
    } catch (error) {
      this.logger.warn(
        `touch session failed: ${error instanceof Error ? error.message : 'unknown'}`,
      );
    }
  }

  async revokeSession(token: string): Promise<void> {
    await this.db.query(
      `UPDATE control_plane.operator_sessions
          SET revoked_at = now()
        WHERE token_hash = $1 AND revoked_at IS NULL`,
      [sessionKey(token)],
    );
  }

  async revokeAllForOperator(operatorId: string): Promise<number> {
    const rows = await this.db.query<{ id: string }>(
      `UPDATE control_plane.operator_sessions
          SET revoked_at = now()
        WHERE operator_id = $1 AND revoked_at IS NULL
        RETURNING id::text`,
      [operatorId],
    );
    return rows.length;
  }

  /** Remove sessions that expired long enough ago to be useless. */
  async pruneExpired(olderThanDays = 7): Promise<number> {
    const rows = await this.db.query<{ id: string }>(
      `DELETE FROM control_plane.operator_sessions
        WHERE expires_at < now() - ($1 || ' days')::interval
        RETURNING id::text`,
      [String(olderThanDays)],
    );
    return rows.length;
  }

  async countOperators(): Promise<number> {
    const row = await this.db.queryOne<{ count: string }>(
      'SELECT count(*)::text AS count FROM control_plane.operators',
    );
    return Number(row?.count ?? 0);
  }

  async findByIdentifier(identifier: string): Promise<OperatorRecord | null> {
    const row = await this.db.queryOne<OperatorRow>(
      `SELECT id::text, username, email, display_name, role, is_active
         FROM control_plane.operators
        WHERE username = $1 OR lower(email) = lower($1)`,
      [identifier],
    );
    return row === null ? null : toRecord(row);
  }

  async createOperator(input: {
    username: string;
    email: string;
    displayName?: string;
    role: Role;
    password: string;
  }): Promise<OperatorRecord> {
    const passwordHash = await hashPassword(input.password);
    const row = await this.db.queryOne<OperatorRow>(
      `INSERT INTO control_plane.operators
         (id, username, email, display_name, role, password_hash)
       VALUES ($1, $2, lower($3), $4, $5, $6)
       RETURNING id::text, username, email, display_name, role, is_active`,
      [
        randomUUID(),
        input.username,
        input.email,
        input.displayName || input.username,
        input.role,
        passwordHash,
      ],
    );
    if (row === null) {
      throw new Error('operator insert returned no row');
    }
    return toRecord(row);
  }

  async setPassword(operatorId: string, password: string): Promise<void> {
    const passwordHash = await hashPassword(password);
    await this.db.query(
      `UPDATE control_plane.operators
          SET password_hash = $2, is_active = TRUE, updated_at = now()
        WHERE id = $1`,
      [operatorId, passwordHash],
    );
    // A password change must not leave older sessions usable.
    await this.revokeAllForOperator(operatorId);
  }
}

/**
 * A real scrypt digest of a value nobody holds, used only to spend the
 * same CPU time on a missing account as on a wrong password.
 */
const DUMMY_HASH =
  'scrypt$32768$8$1$AAAAAAAAAAAAAAAAAAAAAA==$' +
  'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==';
