// Position → order package → bracket history, for the trade-card chart
// (UI-CHART-BRACKET-HISTORY, UI workplan §3).
//
// `/api/bot/positions` rows carry no order-package id, but `/order-packages`
// rows carry `linkedTradeId` == the position's `id`. One shared, 60 s-cached
// package read serves every open card, instead of a fetch per card.
import { api, type BracketHistory } from "./api";

let pkgCache: { at: number; p: Promise<Map<string, any>> } | null = null;

/** linkedTradeId → the full order-package row (signalLogic, meta, modelScores, claudeScore …). */
function packageIndex(): Promise<Map<string, any>> {
  if (pkgCache && Date.now() - pkgCache.at < 60_000) return pkgCache.p;
  const p = api.orderPackages({ includePaper: true, limit: 200 }).then((r: any) => {
    const rows: any[] = Array.isArray(r) ? r : r?.rows ?? [];
    const m = new Map<string, any>();
    for (const x of rows) if (x?.linkedTradeId != null && x?.orderPackageId) m.set(String(x.linkedTradeId), x);
    return m;
  });
  pkgCache = { at: Date.now(), p };
  p.catch(() => (pkgCache = null));
  return p;
}

/** Bracket history for an open position, or null when no package links to it (rendered as "no record"). */
export async function bracketsForPosition(positionId: string, interval: string): Promise<BracketHistory | null> {
  const pkg = (await packageIndex()).get(String(positionId));
  if (!pkg) return null;
  return api.bracketsHistory({ orderPackageId: String(pkg.orderPackageId) }, interval);
}

/** The order package an open position was opened from, or null (no linked package in the last 200). */
export async function packageForPosition(positionId: string): Promise<any | null> {
  return (await packageIndex()).get(String(positionId)) ?? null;
}

/**
 * The order package a CLOSED trade was opened from. `/order-packages` has no
 * linked-trade filter, so: the shared recent index first, else one narrow read —
 * packages for the trade's strategy created from 5 min before it opened — matched
 * on `linkedTradeId`. null = not found (rendered "no linked order package").
 */
export async function packageForClosedTrade(t: { id?: unknown; openedAt?: string | null; strategy?: string | null; pattern?: string | null }): Promise<any | null> {
  if (t.id == null) return null;
  const id = String(t.id);
  const hit = (await packageIndex()).get(id);
  if (hit) return hit;
  const opened = t.openedAt ? Date.parse(t.openedAt) : NaN;
  if (Number.isNaN(opened)) return null;
  const r: any = await api.orderPackages({
    since: new Date(opened - 5 * 60_000).toISOString(),
    strategy: t.strategy ?? t.pattern ?? undefined,
    includePaper: true, limit: 50,
  });
  const rows: any[] = Array.isArray(r) ? r : r?.rows ?? [];
  return rows.find((x) => String(x?.linkedTradeId) === id) ?? null;
}
