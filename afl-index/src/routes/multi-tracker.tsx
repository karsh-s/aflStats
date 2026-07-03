import { createFileRoute } from "@tanstack/react-router";
import { useState, useMemo, useEffect, useRef } from "react";
import { PageShell } from "@/components/page-shell";
import { ApiLoading, ApiOfflineBanner } from "@/components/api-status";
import {
  useTrackerBets,
  useCurrentMultis,
  useAutoPlace,
  useCheckResults,
  useLiveGames,
} from "@/lib/queries";
import { TEAM_LOGOS, TEAM_CODE_BY_NAME, TEAM_COLORS, type TeamCode } from "@/lib/afl-data";
import type { TrackerBet, CurrentGame, TrackerLeg, MultiType, LiveGame } from "@/lib/api";

export const Route = createFileRoute("/multi-tracker")({
  head: () => ({
    meta: [
      { title: "Multi Tracker · AFL.Index" },
      { name: "description", content: "Track $5 SGM multis across all AFL games — P/L by strategy, history, auto result checking." },
    ],
  }),
  component: MultiTrackerPage,
});

// ── Constants ──────────────────────────────────────────────────────────────

const STAKE = 5;

const MULTI_ORDER: MultiType[] = [
  "risk_low", "risk_med", "risk_high",
  "target_2", "target_3", "target_5", "target_10",
];

const MULTI_META: Record<MultiType, { label: string; short: string; badgeCls: string; headerCls: string }> = {
  risk_low:  { label: "LOW RISK",    short: "LOW",   badgeCls: "bg-green-700 text-white",  headerCls: "border-green-700 text-green-700" },
  risk_med:  { label: "MED RISK",    short: "MED",   badgeCls: "bg-yellow-600 text-white", headerCls: "border-yellow-600 text-yellow-700" },
  risk_high: { label: "HIGH RISK",   short: "HIGH",  badgeCls: "bg-red-700 text-white",    headerCls: "border-red-700 text-red-700" },
  target_2:  { label: "TARGET ~2×",  short: "2×",    badgeCls: "bg-ink text-paper",        headerCls: "border-ink text-ink" },
  target_3:  { label: "TARGET ~3×",  short: "3×",    badgeCls: "bg-ink text-paper",        headerCls: "border-ink text-ink" },
  target_5:  { label: "TARGET ~5×",  short: "5×",    badgeCls: "bg-ink text-paper",        headerCls: "border-ink text-ink" },
  target_10: { label: "TARGET ~10×", short: "10×",   badgeCls: "bg-ink text-paper",        headerCls: "border-ink text-ink" },
};

// ── Live score helpers ─────────────────────────────────────────────────────

const _LIVE_NORM: Record<string, string> = {
  "GWS": "Greater Western Sydney",
  "Brisbane": "Brisbane Lions",
  "Geelong": "Geelong Cats",
  "North Melb.": "North Melbourne",
};
function normForLive(t: string) { return _LIVE_NORM[t] ?? t; }

const LIVE_STATUSES = new Set(["Q1", "Q2", "Q3", "Q4", "HT", "OT", "BT"]);

function findLiveGame(liveGames: LiveGame[], home: string, away: string): LiveGame | undefined {
  const h = normForLive(home);
  const a = normForLive(away);
  return liveGames.find(
    (g) => (g.home === h && g.away === a) || (g.home === a && g.away === h),
  );
}

function getLogo(name: string): string | null {
  const code = TEAM_CODE_BY_NAME[name] as TeamCode | undefined;
  return code ? TEAM_LOGOS[code] : null;
}
function getColor(name: string): string {
  const code = TEAM_CODE_BY_NAME[name] as TeamCode | undefined;
  return code ? TEAM_COLORS[code] : "#888";
}

// ── Live score bar ─────────────────────────────────────────────────────────

function LiveScoreBar({ lg, home, away, compact }: { lg: LiveGame; home: string; away: string; compact?: boolean }) {
  const isLive = LIVE_STATUSES.has(lg.status);
  const isFt   = lg.status === "FT";
  if (!isLive && !isFt) return null;

  const homeIsApiHome = lg.home === normForLive(home);
  const hs = homeIsApiHome ? lg.home_score  : lg.away_score;
  const as_ = homeIsApiHome ? lg.away_score : lg.home_score;
  const hg  = homeIsApiHome ? lg.home_goals  : lg.away_goals;
  const hb  = homeIsApiHome ? lg.home_behinds : lg.away_behinds;
  const ag  = homeIsApiHome ? lg.away_goals  : lg.home_goals;
  const ab  = homeIsApiHome ? lg.away_behinds : lg.home_behinds;
  const leading = hs > as_ ? "home" : as_ > hs ? "away" : null;

  if (compact) {
    return (
      <span className="inline-flex items-center gap-1.5 font-mono text-[10px]">
        {isLive && <span className="size-1.5 rounded-full bg-accent animate-pulse shrink-0" />}
        <span className="font-bold text-accent">{lg.status}</span>
        <span className={leading === "home" ? "font-bold text-ink" : "text-muted-foreground"}>{hs}</span>
        <span className="text-muted-foreground">–</span>
        <span className={leading === "away" ? "font-bold text-ink" : "text-muted-foreground"}>{as_}</span>
      </span>
    );
  }

  return (
    <div className={`flex items-center justify-between px-4 py-2 text-xs ${isLive ? "bg-accent/5 border-b border-accent/20" : "bg-ink/5 border-b border-border"}`}>
      <div className="flex items-center gap-2">
        {isLive && <span className="size-2 rounded-full bg-accent animate-pulse" />}
        <span className={`font-mono font-bold uppercase ${isLive ? "text-accent" : "text-muted-foreground"}`}>
          {isFt ? "Final" : lg.status_long}
        </span>
      </div>
      <div className="flex items-center gap-3">
        {/* Home team */}
        <div className="flex items-center gap-1.5">
          {getLogo(home) && <img src={getLogo(home)!} alt={home} className="size-4" />}
          <span className="font-sans text-[11px] font-bold text-muted-foreground">{home}</span>
          <div className="text-right">
            <span className={`font-mono font-extrabold text-sm ${leading === "home" ? "text-ink" : "text-muted-foreground"}`}>{hs}</span>
            <span className="font-mono text-[9px] text-muted-foreground ml-1">{hg}.{hb}</span>
          </div>
        </div>
        <span className="font-mono text-xs text-muted-foreground/50">—</span>
        {/* Away team */}
        <div className="flex items-center gap-1.5">
          <div className="text-left">
            <span className="font-mono text-[9px] text-muted-foreground mr-1">{ag}.{ab}</span>
            <span className={`font-mono font-extrabold text-sm ${leading === "away" ? "text-ink" : "text-muted-foreground"}`}>{as_}</span>
          </div>
          <span className="font-sans text-[11px] font-bold text-muted-foreground">{away}</span>
          {getLogo(away) && <img src={getLogo(away)!} alt={away} className="size-4" />}
        </div>
      </div>
      {isFt && <span className="font-mono text-[9px] font-bold text-muted-foreground">FINAL</span>}
    </div>
  );
}

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtDate(iso: string) {
  try {
    return new Date(iso).toLocaleDateString("en-AU", { day: "numeric", month: "short" });
  } catch { return iso; }
}

function pnlStr(n: number) {
  return n >= 0 ? `+$${n.toFixed(2)}` : `-$${Math.abs(n).toFixed(2)}`;
}

function pnlCls(n: number) {
  return n > 0 ? "text-green-700 font-bold" : n < 0 ? "text-red-600" : "text-muted-foreground";
}

function StatusBadge({ status }: { status: TrackerBet["status"] }) {
  if (status === "won")
    return <span className="px-1.5 py-0.5 font-mono text-[9px] font-bold bg-green-700 text-white">WON</span>;
  if (status === "lost")
    return <span className="px-1.5 py-0.5 font-mono text-[9px] font-bold bg-red-700 text-white">LOST</span>;
  return <span className="px-1.5 py-0.5 font-mono text-[9px] font-bold border border-border text-muted-foreground">PENDING</span>;
}

// ── Per-category stats ─────────────────────────────────────────────────────

interface CatStats {
  bets: number; won: number; lost: number; pending: number;
  staked: number; returned: number; netPnl: number; avgOdds: number;
}

function useCategoryStats(bets: TrackerBet[]): Record<MultiType, CatStats> {
  return useMemo(() => {
    const init = (): CatStats => ({ bets: 0, won: 0, lost: 0, pending: 0, staked: 0, returned: 0, netPnl: 0, avgOdds: 0 });
    const stats: Record<string, CatStats> = Object.fromEntries(MULTI_ORDER.map((t) => [t, init()]));
    for (const bet of bets) {
      const s = stats[bet.multi_type];
      if (!s) continue;
      s.bets++;
      if (bet.status === "won") { s.won++; s.staked += bet.stake; s.returned += bet.stake * bet.combined_odds; }
      else if (bet.status === "lost") { s.lost++; s.staked += bet.stake; }
      else s.pending++;
    }
    for (const [type, s] of Object.entries(stats)) {
      s.netPnl = s.returned - s.staked;
      const wonBets = bets.filter((b) => b.multi_type === type && b.status === "won");
      s.avgOdds = wonBets.length ? wonBets.reduce((a, b) => a + b.combined_odds, 0) / wonBets.length : 0;
    }
    return stats as Record<MultiType, CatStats>;
  }, [bets]);
}

// ── Category card ──────────────────────────────────────────────────────────

function CategoryCard({ type, stats }: { type: MultiType; stats: CatStats }) {
  const mm = MULTI_META[type];
  const resolved = stats.won + stats.lost;
  const winRate = resolved ? (stats.won / resolved) * 100 : null;

  return (
    <div className="border border-border bg-card flex flex-col">
      <div className={`border-b-2 px-3 py-2 ${mm.headerCls}`}>
        <span className="font-mono text-[10px] font-bold uppercase">{mm.label}</span>
      </div>
      <div className="p-3 space-y-1.5 flex-1">
        <div className="flex justify-between text-[11px]">
          <span className="text-muted-foreground">Bets</span>
          <span className="font-mono font-bold">{stats.bets}</span>
        </div>
        <div className="flex justify-between text-[11px]">
          <span className="text-muted-foreground">W / L</span>
          <span className="font-mono">
            <span className="text-green-700 font-bold">{stats.won}</span>
            {" / "}
            <span className="text-red-600 font-bold">{stats.lost}</span>
            {stats.pending > 0 && <span className="text-muted-foreground"> ({stats.pending} pend)</span>}
          </span>
        </div>
        <div className="flex justify-between text-[11px]">
          <span className="text-muted-foreground">Win %</span>
          <span className="font-mono font-bold">
            {winRate !== null ? `${winRate.toFixed(0)}%` : "—"}
          </span>
        </div>
        <div className="border-t border-dashed border-border pt-1.5 mt-1">
          <div className="flex justify-between text-[11px]">
            <span className="text-muted-foreground">Staked</span>
            <span className="font-mono">${stats.staked.toFixed(0)}</span>
          </div>
          <div className="flex justify-between text-[11px]">
            <span className="text-muted-foreground">Returned</span>
            <span className="font-mono">${stats.returned.toFixed(2)}</span>
          </div>
          <div className="flex justify-between text-[11px] mt-0.5">
            <span className="font-bold text-[10px] uppercase">Net P/L</span>
            <span className={`font-mono font-bold ${pnlCls(stats.netPnl)}`}>
              {stats.staked > 0 ? pnlStr(stats.netPnl) : "—"}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Overall summary ────────────────────────────────────────────────────────

function OverallSummary({ bets }: { bets: TrackerBet[] }) {
  const placed = bets.length;
  const won = bets.filter((b) => b.status === "won");
  const lost = bets.filter((b) => b.status === "lost");
  const resolved = won.length + lost.length;
  const staked = resolved * STAKE;
  const returned = won.reduce((s, b) => s + b.stake * b.combined_odds, 0);
  const netPnl = returned - staked;
  const winRate = resolved ? (won.length / resolved) * 100 : null;

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
      {[
        { label: "Bets Placed",  value: String(placed) },
        { label: "Total Staked", value: `$${staked.toFixed(0)}` },
        { label: "Returned",     value: `$${returned.toFixed(2)}` },
        { label: "Net P/L",      value: placed ? pnlStr(netPnl) : "—", cls: placed ? pnlCls(netPnl) : "" },
        { label: "Win Rate",     value: winRate !== null ? `${winRate.toFixed(0)}%` : "—" },
      ].map(({ label, value, cls }) => (
        <div key={label} className="border border-border bg-card p-3 text-center">
          <div className="font-mono text-[10px] text-muted-foreground uppercase">{label}</div>
          <div className={`font-display text-xl font-extrabold ${cls ?? ""}`}>{value}</div>
        </div>
      ))}
    </div>
  );
}

// ── History: leg detail row ────────────────────────────────────────────────

function LegRow({ leg, gameLive }: { leg: TrackerLeg; gameLive?: boolean }) {
  const hasResult = leg.result !== null && leg.result !== undefined;
  const dotCls = !hasResult
    ? gameLive ? "bg-accent/60 animate-pulse" : "bg-ink/15"
    : leg.result ? "bg-green-600" : "bg-red-500";

  return (
    <div className="flex items-center gap-3 py-1 text-xs font-mono">
      <span className={`shrink-0 size-2.5 rounded-full ${dotCls}`} />
      <span className="font-sans font-bold min-w-[140px]">{leg.player}</span>
      <span className="capitalize text-muted-foreground">{leg.stat}</span>
      <span className="font-bold">{leg.milestone}</span>
      <span className="ml-auto text-muted-foreground">{leg.odds.toFixed(2)}×</span>
      <span className="text-accent">{(leg.prob * 100).toFixed(0)}%</span>
      {hasResult && leg.actual_value != null && (
        <span className={`font-bold w-8 text-right ${leg.result ? "text-green-700" : "text-red-600"}`}>
          {leg.actual_value}
        </span>
      )}
      {!hasResult && gameLive && (
        <span className="w-8 text-right font-bold text-accent text-[9px] uppercase">live</span>
      )}
    </div>
  );
}

// ── History: expandable bet row ────────────────────────────────────────────

function BetRow({ bet, liveGames }: { bet: TrackerBet; liveGames: LiveGame[] }) {
  const [open, setOpen] = useState(false);
  const mm = MULTI_META[bet.multi_type] ?? MULTI_META.risk_high;
  const pnl = bet.pnl ?? (bet.status === "lost" ? -bet.stake : null);

  // Parse "Home v Away" to find a live game
  const [gameHome, gameAway] = bet.game.split(" v ");
  const lg = bet.status === "pending" ? findLiveGame(liveGames, gameHome ?? "", gameAway ?? "") : undefined;
  const isLiveNow = lg && LIVE_STATUSES.has(lg.status);
  const isFt = lg?.status === "FT";

  return (
    <>
      <tr
        className={`border-b border-border cursor-pointer transition-colors hover:bg-ink/5 ${
          open ? "bg-ink/[0.03]" : ""
        } ${isLiveNow ? "ring-1 ring-inset ring-accent/30" : ""}`}
        onClick={() => setOpen((v) => !v)}
      >
        <td className="p-3 font-mono text-[10px] text-muted-foreground whitespace-nowrap">{fmtDate(bet.game_date)}</td>
        <td className="p-3">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-bold text-xs whitespace-nowrap">{bet.game}</span>
            {lg && <LiveScoreBar lg={lg} home={gameHome ?? ""} away={gameAway ?? ""} compact />}
          </div>
        </td>
        <td className="p-3">
          <span className={`px-1.5 py-0.5 font-mono text-[9px] font-bold ${mm.badgeCls}`}>{mm.short}</span>
        </td>
        <td className="p-3 font-mono text-xs text-center">{bet.legs.length}</td>
        <td className="p-3 font-mono text-xs text-right font-bold">{bet.combined_odds.toFixed(2)}×</td>
        <td className="p-3 font-mono text-xs text-right">${bet.stake.toFixed(0)}</td>
        <td className="p-3 font-mono text-xs text-right text-muted-foreground">${bet.potential_return.toFixed(2)}</td>
        <td className={`p-3 font-mono text-xs text-right ${pnl != null ? pnlCls(pnl) : "text-muted-foreground"}`}>
          {pnl != null ? pnlStr(pnl) : "—"}
        </td>
        <td className="p-3">
          <StatusBadge status={bet.status} />
        </td>
        <td className="p-3 text-[10px] text-muted-foreground">{open ? "▲" : "▼"}</td>
      </tr>
      {open && (
        <tr className="border-b border-border bg-ink/[0.015]">
          <td colSpan={10} className="px-6 py-3">
            {lg && (
              <div className="mb-3 -mx-6 -mt-3">
                <LiveScoreBar lg={lg} home={gameHome ?? ""} away={gameAway ?? ""} />
              </div>
            )}
            <div className="space-y-0.5">
              {bet.legs.map((leg, i) => <LegRow key={i} leg={leg} gameLive={!!isLiveNow} />)}
            </div>
            {bet.result_checked_at && (
              <div className="mt-2 font-mono text-[9px] text-muted-foreground">
                Results checked {fmtDate(bet.result_checked_at)}
              </div>
            )}
            {isLiveNow && !bet.result_checked_at && (
              <div className="mt-2 font-mono text-[9px] text-accent animate-pulse">
                Game in progress — results will auto-check at full time
              </div>
            )}
            {isFt && !bet.result_checked_at && (
              <div className="mt-2 font-mono text-[9px] text-muted-foreground">
                Game finished — waiting for player stats to be published
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

// ── Current round view ─────────────────────────────────────────────────────

function CurrentRound({ currentGames, bets, liveGames }: { currentGames: CurrentGame[]; bets: TrackerBet[]; liveGames: LiveGame[] }) {
  const byEventAndType = useMemo(() => {
    const map = new Map<string, TrackerBet>();
    for (const b of bets) map.set(`${b.event_id}|${b.multi_type}`, b);
    return map;
  }, [bets]);

  if (currentGames.length === 0) {
    return (
      <div className="border border-border p-6 text-center text-sm text-muted-foreground">
        No upcoming games — odds publish closer to game day each round.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {currentGames.map((game) => {
        const lg = findLiveGame(liveGames, game.home, game.away);
        const isLiveNow = lg && LIVE_STATUSES.has(lg.status);
        const homeColor = getColor(game.home);
        const awayColor = getColor(game.away);

        return (
          <div key={game.event_id} className={`border bg-card overflow-hidden ${isLiveNow ? "border-accent/60" : "border-border"}`}>
            {/* Team colour bar */}
            <div className="h-1" style={{ background: `linear-gradient(90deg, ${homeColor} 50%, ${awayColor} 50%)` }} />

            {/* Game header */}
            <div className="flex items-center justify-between border-b border-border bg-ink/5 px-4 py-2.5">
              <div className="flex items-center gap-2">
                {getLogo(game.home) && <img src={getLogo(game.home)!} alt={game.home} className="size-5" />}
                <span className="font-display font-extrabold uppercase tracking-tighter text-sm">{game.home}</span>
                <span className="text-muted-foreground text-xs font-bold">v</span>
                <span className="font-display font-extrabold uppercase tracking-tighter text-sm">{game.away}</span>
                {getLogo(game.away) && <img src={getLogo(game.away)!} alt={game.away} className="size-5" />}
                {isLiveNow && (
                  <span className="flex items-center gap-1 ml-1">
                    <span className="size-1.5 rounded-full bg-accent animate-pulse" />
                    <span className="font-mono text-[9px] font-bold text-accent uppercase">{lg.status_long}</span>
                  </span>
                )}
              </div>
              <span className="font-mono text-[10px] text-muted-foreground">{fmtDate(game.game_date)}</span>
            </div>

            {/* Live score */}
            {lg && <LiveScoreBar lg={lg} home={game.home} away={game.away} />}

            {/* Multis grid */}
            <div className="grid grid-cols-2 divide-x divide-y divide-border sm:grid-cols-4 lg:grid-cols-7">
              {MULTI_ORDER.map((mtype) => {
                const multi = game.multis.find((m) => m.multi_type === mtype);
                const bet = byEventAndType.get(`${game.event_id}|${mtype}`);
                const mm = MULTI_META[mtype];
                return (
                  <div key={mtype} className="px-3 py-2 space-y-1">
                    <div className="flex items-center justify-between gap-1">
                      <span className={`px-1 py-0.5 font-mono text-[8px] font-bold ${mm.badgeCls}`}>{mm.short}</span>
                      {bet && <StatusBadge status={bet.status} />}
                    </div>
                    {multi ? (
                      <>
                        <div className="font-mono text-[10px] font-bold">{multi.combined_odds.toFixed(2)}×</div>
                        <div className="font-mono text-[9px] text-muted-foreground">{multi.legs.length} legs</div>
                        <div className="font-mono text-[9px] text-accent">{(multi.joint_prob * 100).toFixed(0)}% prob</div>
                      </>
                    ) : (
                      <div className="font-mono text-[9px] text-muted-foreground">not built</div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Live status indicator for page header ──────────────────────────────────

function LiveBanner({ liveGames }: { liveGames: LiveGame[] }) {
  const live = liveGames.filter((g) => LIVE_STATUSES.has(g.status));
  if (live.length === 0) return null;
  return (
    <div className="flex items-center gap-2 border border-accent/30 bg-accent/5 px-3 py-1.5 text-xs">
      <span className="size-2 rounded-full bg-accent animate-pulse shrink-0" />
      <span className="font-mono font-bold text-accent">
        {live.length === 1
          ? `${live[0].home} v ${live[0].away} · ${live[0].status_long}`
          : `${live.length} games live`}
      </span>
      <span className="text-muted-foreground font-mono text-[10px] ml-auto">
        Auto-refreshing every 2 min
      </span>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

function MultiTrackerPage() {
  const { data: trackerData, isLoading: betsLoading, isError } = useTrackerBets();
  const { data: currentGames, isLoading: currentLoading } = useCurrentMultis();
  const { data: liveData } = useLiveGames();
  const autoPlace = useAutoPlace();
  const checkMutation = useCheckResults();
  const [tab, setTab] = useState<"upcoming" | "history">("upcoming");
  const autoPlacedRef = useRef(false);

  const liveGames: LiveGame[] = liveData?.games ?? [];
  const bets: TrackerBet[] = trackerData?.bets ?? [];
  const catStats = useCategoryStats(bets);

  // Auto-place on mount
  useEffect(() => {
    if (autoPlacedRef.current) return;
    autoPlacedRef.current = true;
    autoPlace.mutate();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const pendingPastCount = useMemo(() => {
    const now = new Date();
    return bets.filter((b) => b.status === "pending" && new Date(b.game_date) < now).length;
  }, [bets]);

  const isLoading = betsLoading || currentLoading;

  // Sort history: live/pending first, then by date desc
  const sortedBets = useMemo(() => {
    return [...bets].sort((a, b) => {
      const aLive = a.status === "pending" && !!findLiveGame(liveGames, ...((a.game.split(" v ")) as [string, string]));
      const bLive = b.status === "pending" && !!findLiveGame(liveGames, ...((b.game.split(" v ")) as [string, string]));
      if (aLive && !bLive) return -1;
      if (!aLive && bLive) return 1;
      const aPending = a.status === "pending";
      const bPending = b.status === "pending";
      if (aPending && !bPending) return -1;
      if (!aPending && bPending) return 1;
      return new Date(b.game_date).getTime() - new Date(a.game_date).getTime();
    });
  }, [bets, liveGames]);

  return (
    <PageShell>
      <div className="space-y-6">
        {isError && <ApiOfflineBanner />}

        {/* Live banner */}
        <LiveBanner liveGames={liveGames} />

        {/* Header */}
        <div className="flex items-end justify-between border-b-2 border-ink pb-1">
          <div>
            <h2 className="font-display text-2xl font-extrabold uppercase tracking-tighter">
              Multi Tracker
            </h2>
            <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">
              $5 auto-placed per multi · every game · every strategy
            </p>
          </div>
          <button
            onClick={() => checkMutation.mutate()}
            disabled={checkMutation.isPending || pendingPastCount === 0}
            className="mb-1 border border-border px-4 py-1.5 font-mono text-[11px] font-bold uppercase text-muted-foreground transition-colors hover:border-ink hover:text-ink disabled:opacity-40"
          >
            {checkMutation.isPending
              ? "Checking…"
              : pendingPastCount > 0
              ? `Check Results (${pendingPastCount})`
              : "Results Up to Date"}
          </button>
        </div>

        {isLoading && <ApiLoading label="Loading tracker…" />}

        {bets.length > 0 && <OverallSummary bets={bets} />}

        {bets.length > 0 && (
          <div>
            <div className="mb-2 font-mono text-[10px] font-bold uppercase text-muted-foreground">
              P/L by Strategy
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
              {MULTI_ORDER.map((type) => (
                <CategoryCard key={type} type={type} stats={catStats[type]} />
              ))}
            </div>
          </div>
        )}

        {/* Tabs */}
        <div className="flex gap-0 border-b border-border">
          {(["upcoming", "history"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`border-b-2 px-6 py-2.5 text-[11px] font-bold uppercase tracking-widest transition-colors ${
                tab === t
                  ? "-mb-px border-ink text-ink"
                  : "border-transparent text-muted-foreground hover:text-ink"
              }`}
            >
              {t === "upcoming" ? "Upcoming" : `All Bets (${bets.length})`}
            </button>
          ))}
        </div>

        {/* Upcoming tab */}
        {tab === "upcoming" && (
          <>
            {currentLoading && <ApiLoading label="Building multis…" />}
            {currentGames && (
              <CurrentRound currentGames={currentGames} bets={bets} liveGames={liveGames} />
            )}
          </>
        )}

        {/* All Bets tab */}
        {tab === "history" && (
          bets.length === 0 ? (
            <div className="border border-border p-8 text-center text-sm text-muted-foreground">
              No bets yet — multis will be auto-placed for all upcoming games on page load.
            </div>
          ) : (
            <div className="border border-border bg-card overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-border text-[10px] font-bold uppercase text-muted-foreground">
                    <th className="p-3">Date</th>
                    <th className="p-3">Game</th>
                    <th className="p-3">Type</th>
                    <th className="p-3 text-center">Legs</th>
                    <th className="p-3 text-right">Odds</th>
                    <th className="p-3 text-right">Stake</th>
                    <th className="p-3 text-right">Pot. Return</th>
                    <th className="p-3 text-right">P/L</th>
                    <th className="p-3">Status</th>
                    <th className="p-3" />
                  </tr>
                </thead>
                <tbody>
                  {sortedBets.map((bet) => (
                    <BetRow key={bet.id} bet={bet} liveGames={liveGames} />
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}

        <p className="text-[10px] text-muted-foreground max-w-prose">
          $5 stake is hypothetical — for tracking purposes only. Results auto-check once player stats
          are updated after each game. The Odds API removes events once they start, so multis for games
          in progress cannot be retroactively placed. Gamble responsibly — 18+.
        </p>
      </div>
    </PageShell>
  );
}
