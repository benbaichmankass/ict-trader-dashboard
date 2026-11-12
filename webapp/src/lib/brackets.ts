// Position → order package → bracket history, for the trade-card chart
// (UI-CHART-BRACKET-HISTORY, UI workplan §3).
//
// `/api/bot/positions` rows carry no order-package id, but `/order-packages`
// rows carry `linkedTradeId` == the position's `id`. One shared, 60 s-cached
// package read serves every open card, instead of a fetch per card.
import { api, type BracketHistory } from "./api";

let pkgCache: { at: number; p: Promise<Map<string, string>> } | null = null;

function packageIndex(): Promise<Map<string, string>> {
  if (pkgCache && Date.now() - pkgCache.at < 60_000) return pkgCache.p;
  const p = api.orderPackages({ includePaper: true, limit: 200 }).then((r: any) => {
    const rows: any[] = Array.isArray(r) ? r : r?.rows ?? [];
    const m = new Map<string, string>();
    for (const x of rows) if (x?.linkedTradeId != null && x?.orderPackageId) m.set(String(x.linkedTradeId), String(x.orderPackageId));
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
  return api.bracketsHistory({ orderPackageId: pkg }, interval);
}
