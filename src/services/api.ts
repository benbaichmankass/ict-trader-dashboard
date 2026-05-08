import { BotStats, LogEntry, Position, Signal } from '../types';

const BOT_API = import.meta.env.VITE_BOT_API_URL ?? '';
const DEFAULT_TIMEOUT_MS = 8_000;

export class BotApiError extends Error {
  constructor(
    public readonly endpoint: string,
    public readonly httpStatus: number,
    message: string,
  ) {
    super(message);
    this.name = 'BotApiError';
  }
}

async function fetchJson<T>(path: string, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T> {
  const url = `${BOT_API}${path}`;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: ctrl.signal });
    if (!res.ok) {
      throw new BotApiError(path, res.status, `HTTP ${res.status} on ${path}`);
    }
    return (await res.json()) as T;
  } catch (err) {
    if (err instanceof BotApiError) throw err;
    // Network error, abort, or JSON parse failure — surface as a 0-status BotApiError
    // so callers can branch on `instanceof BotApiError` uniformly.
    const msg = err instanceof Error ? err.message : String(err);
    throw new BotApiError(path, 0, msg);
  } finally {
    clearTimeout(timer);
  }
}

export const getStats = (): Promise<BotStats> => fetchJson<BotStats>('/api/bot/stats');
export const getLogs = (): Promise<LogEntry[]> => fetchJson<LogEntry[]>('/api/bot/logs');
export const getPositions = (): Promise<Position[]> => fetchJson<Position[]>('/api/bot/positions');
export const getSignals = (): Promise<Signal[]> => fetchJson<Signal[]>('/api/bot/signals');

export interface SectionResult<T> {
  data: T | null;
  error: BotApiError | null;
}

export interface DashboardSnapshot {
  stats: SectionResult<BotStats>;
  logs: SectionResult<LogEntry[]>;
  positions: SectionResult<Position[]>;
  signals: SectionResult<Signal[]>;
  /** True when every section failed — i.e. the bot is unreachable. */
  allFailed: boolean;
}

function settle<T>(p: PromiseSettledResult<T>): SectionResult<T> {
  if (p.status === 'fulfilled') return { data: p.value, error: null };
  const err = p.reason instanceof BotApiError
    ? p.reason
    : new BotApiError('?', 0, p.reason instanceof Error ? p.reason.message : String(p.reason));
  return { data: null, error: err };
}

export async function getDashboardSnapshot(): Promise<DashboardSnapshot> {
  const [stats, logs, positions, signals] = await Promise.allSettled([
    getStats(),
    getLogs(),
    getPositions(),
    getSignals(),
  ]);
  const result = {
    stats: settle(stats),
    logs: settle(logs),
    positions: settle(positions),
    signals: settle(signals),
    allFailed: false,
  };
  result.allFailed =
    !!result.stats.error && !!result.logs.error && !!result.positions.error && !!result.signals.error;
  return result;
}
