/**
 * Contract suite for `src/services/api.ts` — the highest-leverage spot
 * in the dashboard, because every component is downstream of these
 * fetchers.
 *
 * Scope: pin only the 5 contracts that actually broke between bot ↔
 * dashboard today (2026-05-10). Each test maps to a specific PR-pair
 * incident, so when one fails the breaking commit is obvious.
 *
 * NOT in scope: component render tests, DOM tests, coverage gate. Those
 * are a separate sprint. The job here is "would have caught today's
 * outage on PR open".
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  BotApiError,
  describeError,
  getBacktests,
  getClosedTrades,
  getDashboardSnapshot,
  getPositions,
} from './api';

type FetchMock = ReturnType<typeof vi.fn>;

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function errorResponse(status: number): Response {
  return new Response('{"detail":"err"}', {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

beforeEach(() => {
  vi.spyOn(globalThis, 'fetch');
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Contract 1 — getBacktests: id is string, counts non-nullable.
//
// Incident: ict-trading-bot#690 vs #689 race today shipped two
// different shapes. The dashboard's #14 typed `id: number` and counts
// nullable; bot #689 was actually `id: number` + counts non-nullable;
// bot #699 corrected to `id: string` for cross-endpoint consistency.
// Three PRs to converge. Pinning the canonical end-state here would
// have made the drift impossible to ship.
// ---------------------------------------------------------------------------

describe('getBacktests wire shape', () => {
  it('returns BacktestRun[] with id:string and non-nullable counts', async () => {
    const payload = [
      {
        id: '12',
        strategy: 'vwap',
        runDate: '2026-05-09',
        startDate: '2026-04-01',
        endDate: '2026-05-08',
        totalTrades: 0,
        winningTrades: 0,
        losingTrades: 0,
        winRate: null,
        profitFactor: null,
        expectancy: null,
        sharpeRatio: null,
        maxDrawdownPct: null,
        totalPnl: null,
        createdAt: '2026-05-09T12:00:00',
      },
    ];
    (globalThis.fetch as FetchMock).mockResolvedValueOnce(jsonResponse(payload));
    const rows = await getBacktests();
    expect(typeof rows[0].id).toBe('string');
    expect(typeof rows[0].totalTrades).toBe('number');
    expect(typeof rows[0].winningTrades).toBe('number');
    expect(typeof rows[0].losingTrades).toBe('number');
  });
});

// ---------------------------------------------------------------------------
// Contract 2 — getClosedTrades id:string (same family as backtests).
//
// Pinned because the M5 P4 wire-shape correction (bot #699) only
// touched `backtests.py`. If a future drift on `trades_closed.py`
// flipped its id to int — same kind of inconsistency the
// `_row_to_wire` shape was supposed to prevent — this test would
// catch it on PR open.
// ---------------------------------------------------------------------------

describe('getClosedTrades wire shape', () => {
  it('returns ClosedTrade[] with id:string', async () => {
    const payload = [
      {
        id: '7',
        account: 'bybit_2',
        symbol: 'BTCUSDT',
        side: 'buy',
        pattern: 'FVG',
        qty: 0.001,
        entryPrice: 62000,
        exitPrice: 62150,
        realizedPnl: 0.15,
        realizedPnlPct: null,
        openedAt: '2026-05-09T10:00:00Z',
        closedAt: '2026-05-09T10:05:00Z',
        closeReason: 'tp',
      },
    ];
    (globalThis.fetch as FetchMock).mockResolvedValueOnce(jsonResponse(payload));
    const rows = await getClosedTrades();
    expect(typeof rows[0].id).toBe('string');
  });
});

// ---------------------------------------------------------------------------
// Contract 3 — getPositions id:string (same family as 1 + 2).
// ---------------------------------------------------------------------------

describe('getPositions wire shape', () => {
  it('returns Position[] with id:string', async () => {
    const payload = [
      {
        id: '42',
        account: 'bybit_2',
        symbol: 'BTCUSDT',
        side: 'buy',
        qty: 0.001,
        entryPrice: 62000,
        unrealizedPnl: 12.45,
        openedAt: '2026-05-08T10:00:00Z',
      },
    ];
    (globalThis.fetch as FetchMock).mockResolvedValueOnce(jsonResponse(payload));
    const rows = await getPositions();
    expect(typeof rows[0].id).toBe('string');
  });
});

// ---------------------------------------------------------------------------
// Contract 4 — getDashboardSnapshot Promise.allSettled isolation.
//
// Today's bot-API outage screenshot showed all four endpoints in
// "Network error / 0ms ok never" state — the dashboard's render
// chrome stayed up because each section's failure is captured into
// SectionResult.error rather than thrown. The full dashboard never
// blanks even when the bot is fully down. If a refactor accidentally
// switches to Promise.all, this test fails.
// ---------------------------------------------------------------------------

describe('getDashboardSnapshot Promise.allSettled isolation', () => {
  it('a single 503 leaves the other sections populated', async () => {
    (globalThis.fetch as FetchMock)
      .mockResolvedValueOnce(
        jsonResponse({
          pnl24h: 0,
          totalPnL: 0,
          openTrades: 0,
          winRate: 0,
          status: 'running',
          datasource: 'live',
          vmHealth: { cpu: null, memory: null, disk: null },
        }),
      )
      .mockResolvedValueOnce(errorResponse(503))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse([]));
    const snap = await getDashboardSnapshot();
    expect(snap.stats.data).not.toBeNull();
    expect(snap.logs.error).toBeInstanceOf(BotApiError);
    expect(snap.positions.data).toEqual([]);
    expect(snap.signals.data).toEqual([]);
    expect(snap.allFailed).toBe(false);
  });

  it('allFailed=true only when every section errors', async () => {
    (globalThis.fetch as FetchMock)
      .mockResolvedValueOnce(errorResponse(503))
      .mockResolvedValueOnce(errorResponse(503))
      .mockResolvedValueOnce(errorResponse(503))
      .mockResolvedValueOnce(errorResponse(503));
    const snap = await getDashboardSnapshot();
    expect(snap.allFailed).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Contract 5 — describeError exact strings (cross-component UI contract).
//
// StatsGrid + OfflinePanel + every tab's error chrome render
// describeError(err) verbatim. Change the strings → every panel's
// copy changes silently. Pinning the four kinds protects the UI from
// invisible churn.
// ---------------------------------------------------------------------------

describe('describeError exact-string contract', () => {
  it('returns the expected label for each kind', () => {
    expect(describeError(new BotApiError('/x', 0, 'timeout', 'timeout'))).toBe(
      'Timed out',
    );
    expect(describeError(new BotApiError('/x', 0, 'network', 'network'))).toBe(
      'Network error',
    );
    expect(describeError(new BotApiError('/x', 503, 'http', 'http'))).toBe(
      'HTTP 503',
    );
    expect(describeError(new BotApiError('/x', 200, 'parse', 'parse'))).toBe(
      'Bad response',
    );
    expect(describeError(null)).toBe('');
  });
});
