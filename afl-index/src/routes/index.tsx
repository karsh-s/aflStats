import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, useMemo, useEffect, useRef } from "react";
import { PageShell, SectionHeading } from "@/components/page-shell";
import { LadderTable } from "@/components/ladder-table";
import { InsightCard } from "@/components/insight-card";
import { ApiOfflineBanner, ApiLoading } from "@/components/api-status";
import { INSIGHTS, TEAM_COLORS, TEAM_LOGOS, TEAM_CODE_BY_NAME, type TeamCode } from "@/lib/afl-data";
import { useEvents, useValueBets, useHistoricalRounds, useHistoricalRound, useLiveGames, useLiveRefresh } from "@/lib/queries";
import type { APIEvent, APIValueBet, HistoricalRound, HistoricalGame, LiveGame } from "@/lib/api";

function getTeamCode(name: string): TeamCode | null {
  return (TEAM_CODE_BY_NAME[name] as TeamCode) ?? null;
}
function getTeamColor(name: string): string {
  const code = getTeamCode(name);
  return code ? TEAM_COLORS[code] : "#888";
}
function getTeamLogo(name: string): string | null {
  const code = getTeamCode(name);
  return code ? TEAM_LOGOS[code] : null;
}

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "statsfl — Live Terminal · Predictions & Value" },
      { name: "description", content: "Live AFL model: win probabilities, player props, value bets and same-game multis." },
    ],
  }),
  component: Index,
});

// ── Helpers ────────────────────────────────────────────────────────────────

function WeatherBadge({ rain_mm, wind_kmh }: { rain_mm?: number | null; wind_kmh?: number | null }) {
  const bits: string[] = [];
  if (rain_mm && rain_mm >= 1) bits.push(`${rain_mm.toFixed(0)}mm rain`);
  if (wind_kmh && wind_kmh >= 30) bits.push(`${wind_kmh.toFixed(0)}km/h wind`);
  return <span className="font-mono text-[10px] text-muted-foreground">{bits.length ? bits.join(" · ") : "Fine"}</span>;
}

// ── Live score helpers ─────────────────────────────────────────────────────

/** Normalise team names so Odds API and API-Sports names match */
const _LIVE_NORM: Record<string, string> = {
  "GWS": "Greater Western Sydney",
  "Greater Western Sydney": "Greater Western Sydney",
  "Brisbane": "Brisbane Lions",
  "Geelong": "Geelong Cats",
  "North Melb.": "North Melbourne",
};
function normForLive(t: string) { return _LIVE_NORM[t] ?? t; }

function findLiveGame(liveGames: LiveGame[], home: string, away: string): LiveGame | undefined {
  const h = normForLive(home);
  const a = normForLive(away);
  return liveGames.find(
    (g) => (g.home === h && g.away === a) || (g.home === a && g.away === h),
  );
}

const LIVE_STATUSES = new Set(["Q1", "Q2", "Q3", "Q4", "HT", "OT", "BT"]);

function LiveScoreBadge({ lg, home, away }: { lg: LiveGame; home: string; away: string }) {
  const isLive = LIVE_STATUSES.has(lg.status);
  const isFt   = lg.status === "FT";
  if (!isLive && !isFt) return null;

  const homeScore = lg.home === normForLive(home) ? lg.home_score : lg.away_score;
  const awayScore = lg.home === normForLive(home) ? lg.away_score : lg.home_score;
  const homeGoals = lg.home === normForLive(home) ? lg.home_goals : lg.away_goals;
  const homeBeh   = lg.home === normForLive(home) ? lg.home_behinds : lg.away_behinds;
  const awayGoals = lg.home === normForLive(home) ? lg.away_goals : lg.home_goals;
  const awayBeh   = lg.home === normForLive(home) ? lg.away_behinds : lg.home_behinds;
  const leading   = homeScore > awayScore ? "home" : awayScore > homeScore ? "away" : null;

  return (
    <div className={`mt-2 border-t pt-2 ${isLive ? "border-accent/40" : "border-dashed border-border"}`}>
      {isLive && (
        <div className="flex items-center gap-1.5 mb-1.5">
          <span className="size-1.5 rounded-full bg-accent animate-pulse" />
          <span className="font-mono text-[9px] font-bold uppercase text-accent">{lg.status_long}</span>
        </div>
      )}
      {isFt && (
        <div className="mb-1.5">
          <span className="font-mono text-[9px] font-bold uppercase text-muted-foreground">Final Score</span>
        </div>
      )}
      <div className="flex items-center justify-between">
        <span className={`font-display text-lg font-extrabold ${leading === "home" ? "text-ink" : "text-muted-foreground"}`}>
          {homeScore}
          <span className="font-mono text-[9px] font-normal ml-1 text-muted-foreground">{homeGoals}.{homeBeh}</span>
        </span>
        <span className="font-mono text-[10px] text-muted-foreground">—</span>
        <span className={`font-display text-lg font-extrabold ${leading === "away" ? "text-ink" : "text-muted-foreground"}`}>
          {awayScore}
          <span className="font-mono text-[9px] font-normal ml-1 text-muted-foreground">{awayGoals}.{awayBeh}</span>
        </span>
      </div>
    </div>
  );
}

// ── Current round: live game card ──────────────────────────────────────────

function GameCard({ ev, liveGames }: { ev: APIEvent; liveGames: LiveGame[] }) {
  const homeWins = ev.p_home >= 0.5;
  const maxP = Math.max(ev.p_home, ev.p_away);
  const conf = maxP >= 0.70 ? "High" : maxP >= 0.58 ? "Med" : "Low";
  const confCls = conf === "High" ? "bg-ink text-paper" : conf === "Med" ? "bg-ink/10 text-ink" : "text-muted-foreground border border-border";

  const homeColor = getTeamColor(ev.home);
  const awayColor = getTeamColor(ev.away);
  const homeLogo = getTeamLogo(ev.home);
  const awayLogo = getTeamLogo(ev.away);
  const liveGame = findLiveGame(liveGames, ev.home, ev.away);
  const isLiveNow = liveGame && LIVE_STATUSES.has(liveGame.status);

  return (
    <Link
      to="/game/$eventId"
      params={{ eventId: ev.id }}
      className={`group block border bg-card transition-colors hover:border-ink/40 overflow-hidden ${isLiveNow ? "border-accent/60" : "border-border"}`}
    >
      <div className="h-1" style={{ background: `linear-gradient(90deg, ${homeColor} 50%, ${awayColor} 50%)` }} />
      <div className="p-4">
        <div className="mb-3 flex items-start justify-between gap-2">
          <div className="flex-1 space-y-2">
            <div className="flex items-center gap-2">
              {homeLogo ? (
                <img src={homeLogo} alt={ev.home} className="size-6 object-contain shrink-0" />
              ) : (
                <span className="size-2.5 rounded-full shrink-0" style={{ background: homeColor }} />
              )}
              <span className={`text-sm font-bold ${homeWins ? "text-ink" : "text-muted-foreground"}`}>{ev.home}</span>
              <span className={`font-mono text-[11px] font-bold ml-auto ${homeWins ? "text-ink" : "text-muted-foreground"}`}>
                {(ev.p_home * 100).toFixed(0)}%
              </span>
            </div>
            <div className="flex items-center gap-2">
              {awayLogo ? (
                <img src={awayLogo} alt={ev.away} className="size-6 object-contain shrink-0" />
              ) : (
                <span className="size-2.5 rounded-full shrink-0" style={{ background: awayColor }} />
              )}
              <span className={`text-sm font-bold ${!homeWins ? "text-ink" : "text-muted-foreground"}`}>{ev.away}</span>
              <span className={`font-mono text-[11px] font-bold ml-auto ${!homeWins ? "text-ink" : "text-muted-foreground"}`}>
                {(ev.p_away * 100).toFixed(0)}%
              </span>
            </div>
          </div>
          <div className="shrink-0 text-right">
            <span className={`px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase ${confCls}`}>{conf}</span>
            <div className="mt-1 font-mono text-[10px] text-muted-foreground">
              {new Date(ev.commence_time).toLocaleString(undefined, {
                weekday: "short", day: "numeric", month: "short",
                hour: "numeric", minute: "2-digit", hour12: true,
              })}
            </div>
          </div>
        </div>
        <div className="mb-3 flex h-1.5 overflow-hidden bg-ink/5 rounded-full">
          <div className="h-full rounded-l-full" style={{ width: `${ev.p_home * 100}%`, background: homeColor }} />
          <div className="h-full rounded-r-full" style={{ width: `${ev.p_away * 100}%`, background: awayColor, opacity: 0.65 }} />
        </div>
        <div className="flex items-center justify-between">
          <span className="font-mono text-[10px] text-muted-foreground">{ev.venue}</span>
          <WeatherBadge rain_mm={ev.rain_mm} wind_kmh={ev.wind_kmh} />
        </div>
        {ev.top_disposals.length > 0 && (
          <div className="mt-2.5 border-t border-dashed border-border pt-2.5 text-[10px]">
            <span className="font-bold uppercase text-muted-foreground mr-1">Disp:</span>
            {ev.top_disposals.slice(0, 2).map(([name, , val]) => (
              <span key={name} className="mr-2 text-muted-foreground">
                {name} <span className="font-mono font-bold text-ink">{val}</span>
              </span>
            ))}
            {ev.top_goals.length > 0 && (
              <>
                <span className="font-bold uppercase text-muted-foreground mx-1">· Goals:</span>
                {ev.top_goals.slice(0, 1).map(([name, , val]) => (
                  <span key={name} className="text-muted-foreground">
                    {name} <span className="font-mono font-bold text-ink">{val.toFixed(1)}</span>
                  </span>
                ))}
              </>
            )}
          </div>
        )}
        {liveGame && <LiveScoreBadge lg={liveGame} home={ev.home} away={ev.away} />}
        <div className="mt-2 font-mono text-[10px] font-bold uppercase text-accent opacity-0 transition-opacity group-hover:opacity-100">
          Props + lines →
        </div>
      </div>
    </Link>
  );
}

// ── Historical round: game result card ─────────────────────────────────────

function HistoricalGameCard({ game, liveGames }: { game: HistoricalGame; liveGames?: LiveGame[] }) {
  const liveGame = liveGames ? findLiveGame(liveGames, game.home, game.away) : undefined;
  // Prefer live API scores over scraped stats scores
  const hs = liveGame?.status === "FT" && liveGame.home === normForLive(game.home)
    ? liveGame.home_score : game.home_score;
  const as_ = liveGame?.status === "FT" && liveGame.home === normForLive(game.home)
    ? liveGame.away_score : game.away_score;
  const hg = liveGame?.status === "FT" && liveGame.home === normForLive(game.home)
    ? liveGame.home_goals : game.home_goals;
  const hb = liveGame?.status === "FT" && liveGame.home === normForLive(game.home)
    ? liveGame.home_behinds : game.home_behinds;
  const ag = liveGame?.status === "FT" && liveGame.home === normForLive(game.home)
    ? liveGame.away_goals : game.away_goals;
  const ab = liveGame?.status === "FT" && liveGame.home === normForLive(game.home)
    ? liveGame.away_behinds : game.away_behinds;

  const homeWon = hs > as_;
  const awayWon = as_ > hs;
  const homeColor = getTeamColor(game.home);
  const awayColor = getTeamColor(game.away);
  const homeLogo = getTeamLogo(game.home);
  const awayLogo = getTeamLogo(game.away);

  return (
    <div className="border border-border bg-card overflow-hidden">
      <div className="h-1" style={{ background: `linear-gradient(90deg, ${homeColor} 50%, ${awayColor} 50%)` }} />
      <div className="p-4">
        <div className="flex items-center justify-between gap-3">
          {/* Home */}
          <div className="flex-1 flex items-center gap-2 min-w-0">
            {homeLogo ? (
              <img src={homeLogo} alt={game.home} className="size-6 object-contain shrink-0" />
            ) : (
              <span className="size-2.5 rounded-full shrink-0" style={{ background: homeColor }} />
            )}
            <span className={`text-sm font-bold truncate ${homeWon ? "text-ink" : "text-muted-foreground"}`}>
              {game.home}
            </span>
          </div>
          {/* Scores */}
          <div className="shrink-0 text-center">
            <div className="flex items-baseline gap-2">
              <span className={`font-display text-xl font-extrabold ${homeWon ? "text-ink" : "text-muted-foreground"}`}>
                {hs}
              </span>
              <span className="font-mono text-[10px] text-muted-foreground">
                {hg}.{hb}
              </span>
              <span className="font-mono text-[11px] text-muted-foreground/50">—</span>
              <span className="font-mono text-[10px] text-muted-foreground">
                {ag}.{ab}
              </span>
              <span className={`font-display text-xl font-extrabold ${awayWon ? "text-ink" : "text-muted-foreground"}`}>
                {as_}
              </span>
            </div>
            {(homeWon || awayWon) && (
              <div className="font-mono text-[9px] text-muted-foreground mt-0.5">
                {homeWon ? game.home : game.away} won by {Math.abs(hs - as_)}
              </div>
            )}
          </div>
          {/* Away */}
          <div className="flex-1 flex items-center justify-end gap-2 min-w-0">
            <span className={`text-sm font-bold truncate text-right ${awayWon ? "text-ink" : "text-muted-foreground"}`}>
              {game.away}
            </span>
            {awayLogo ? (
              <img src={awayLogo} alt={game.away} className="size-6 object-contain shrink-0" />
            ) : (
              <span className="size-2.5 rounded-full shrink-0" style={{ background: awayColor }} />
            )}
          </div>
        </div>

        <div className="mt-2.5 flex items-center justify-between">
          <span className="font-mono text-[10px] text-muted-foreground">{game.venue}</span>
          <span className="font-mono text-[10px] text-muted-foreground">
            {new Date(game.date + "T12:00:00").toLocaleDateString(undefined, {
              weekday: "short", day: "numeric", month: "short", year: "numeric",
            })}
          </span>
        </div>

        {game.top_disposals.length > 0 && (
          <div className="mt-2 border-t border-dashed border-border pt-2 text-[10px]">
            <span className="font-bold uppercase text-muted-foreground mr-1">Best disp:</span>
            {game.top_disposals.slice(0, 2).map(([name, , val]) => (
              <span key={name} className="mr-2 text-muted-foreground">
                {name} <span className="font-mono font-bold text-ink">{val}</span>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Round navigator ────────────────────────────────────────────────────────

// Ordered round labels within a season (numeric 1-25, then finals)
const FINALS_ORDER = ["Elimination Final", "Qualifying Final", "Semi Final", "Preliminary Final", "Grand Final"];
const MAX_ROUNDS = 25;

interface RoundEntry {
  season: number;
  round: string;
  date: string | null;
  hasData: boolean;
}

function buildRoundList(historical: HistoricalRound[]): RoundEntry[] {
  const withData = new Set(historical.map((r) => `${r.season}|${r.round}`));

  const past: RoundEntry[] = historical.map((r) => ({
    season: r.season, round: r.round, date: r.date, hasData: true,
  }));

  // Future 2026 rounds not yet in stats
  const existing2026 = new Set(historical.filter((r) => r.season === 2026).map((r) => r.round));
  const future: RoundEntry[] = [];
  for (let rnd = 1; rnd <= MAX_ROUNDS; rnd++) {
    if (!existing2026.has(String(rnd))) {
      future.push({ season: 2026, round: String(rnd), date: null, hasData: false });
    }
  }
  for (const label of FINALS_ORDER) {
    if (!existing2026.has(label)) {
      future.push({ season: 2026, round: label, date: null, hasData: false });
    }
  }

  return [...past, ...future];
}

function roundLabel(round: string): string {
  const n = Number(round);
  return isNaN(n) ? round : `Round ${n}`;
}

function RoundNav({
  rounds,
  selected,
  onSelect,
}: {
  rounds: RoundEntry[];
  selected: { season: number; round: string } | null;
  onSelect: (r: { season: number; round: string } | null) => void;
}) {
  const seasons = useMemo(() => [...new Set(rounds.map((r) => r.season))].sort((a, b) => a - b), [rounds]);

  const currentLabel = selected
    ? `${selected.season} · ${roundLabel(selected.round)}`
    : "2026 · Current Round";

  // Index in the full list for prev/next — null = "current" (newest)
  const allEntries = useMemo(() => [null, ...rounds].reverse(), [rounds]); // newest first: current, 2026R16, R15, ...
  const currentIdx = selected === null ? 0 : allEntries.findIndex(
    (e) => e !== null && e.season === selected.season && e.round === selected.round
  );

  function go(delta: number) {
    const next = currentIdx + delta;
    if (next < 0 || next >= allEntries.length) return;
    onSelect(allEntries[next] ?? null);
  }

  const seasonRounds = useMemo(() => {
    if (!selected) return [];
    return rounds.filter((r) => r.season === selected.season);
  }, [rounds, selected]);

  return (
    <div className="space-y-2">
      {/* Main nav row */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => go(1)}
          disabled={currentIdx >= allEntries.length - 1}
          className="border border-border px-2 py-1 font-mono text-[11px] font-bold text-muted-foreground hover:text-ink hover:border-ink disabled:opacity-30 transition-colors"
        >
          ←
        </button>

        <div className="flex-1 flex items-center gap-1.5">
          {/* Season selector */}
          <select
            value={selected?.season ?? "current"}
            onChange={(e) => {
              const val = e.target.value;
              if (val === "current") { onSelect(null); return; }
              const season = Number(val);
              const latest = rounds.filter((r) => r.season === season).at(-1);
              if (latest) onSelect({ season: latest.season, round: latest.round });
            }}
            className="border border-border bg-card px-2 py-1 font-mono text-[11px] font-bold text-ink focus:outline-none focus:border-ink cursor-pointer"
          >
                        {seasons.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>

          {selected && (
            <>
              <span className="font-mono text-[10px] text-muted-foreground">·</span>
              <select
                value={selected.round}
                onChange={(e) => onSelect({ season: selected.season, round: e.target.value })}
                className="flex-1 border border-border bg-card px-2 py-1 font-mono text-[11px] font-bold text-ink focus:outline-none focus:border-ink cursor-pointer"
              >
                {seasonRounds.map((r) => (
                  <option key={r.round} value={r.round}>
                    {roundLabel(r.round)}{r.hasData ? "" : " (upcoming)"}
                  </option>
                ))}
              </select>
            </>
          )}

          {!selected && (
            <span className="flex-1 border border-border bg-card px-2 py-1 font-mono text-[11px] font-bold text-ink/60">
              {currentLabel}
            </span>
          )}
        </div>

        <button
          onClick={() => go(-1)}
          disabled={currentIdx <= 0}
          className="border border-border px-2 py-1 font-mono text-[11px] font-bold text-muted-foreground hover:text-ink hover:border-ink disabled:opacity-30 transition-colors"
        >
          →
        </button>
      </div>
    </div>
  );
}

// ── Value row ──────────────────────────────────────────────────────────────

const TIER_META: Record<string, { label: string; cls: string }> = {
  lock:   { label: "LOCK",   cls: "bg-ink text-paper" },
  strong: { label: "STRONG", cls: "bg-ink/15 text-ink" },
  value:  { label: "VALUE",  cls: "border border-border text-muted-foreground" },
};

function HitDots({ rate, total }: { rate: number | null; total: number }) {
  if (rate === null || total === 0) {
    return <span className="font-mono text-[9px] text-muted-foreground/30">—</span>;
  }
  const filled = Math.round(rate * total);
  return (
    <span className="flex gap-0.5 items-center">
      {Array.from({ length: total }).map((_, i) => (
        <span key={i} className={`inline-block size-1.5 rounded-full ${i < filled ? "bg-ink" : "bg-ink/15"}`} />
      ))}
    </span>
  );
}

function ValueRow({ bet }: { bet: APIValueBet }) {
  const tm = TIER_META[bet.tier] ?? TIER_META.value;
  const oppDisplay = Math.min(bet.opp_n, 5);
  return (
    <div className="flex items-center gap-2.5 px-3 py-2.5 hover:bg-accent/5 transition-colors border-b border-border last:border-0">
      <span className={`shrink-0 px-1.5 py-0.5 font-mono text-[9px] font-bold ${tm.cls}`}>{tm.label}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="font-bold text-sm">{bet.player}</span>
          <span className="font-mono text-[9px] font-bold text-muted-foreground border border-border px-1 py-px">{bet.team}</span>
        </div>
        <div className="font-mono text-[10px] text-muted-foreground mt-0.5">
          <span className="capitalize">{bet.stat}</span>{" "}
          <span className="font-bold text-ink">{bet.milestone}</span>
          <span className="mx-1 opacity-40">·</span>
          {bet.game}
        </div>
      </div>
      <div className="shrink-0 hidden md:flex flex-col gap-0.5 items-end">
        <div className="flex items-center gap-1">
          <span className="font-mono text-[9px] text-muted-foreground w-6 text-right">L5</span>
          <HitDots rate={bet.hit_last_5} total={5} />
        </div>
        <div className="flex items-center gap-1">
          <span className="font-mono text-[9px] text-muted-foreground w-6 text-right">OPP</span>
          <HitDots rate={bet.hit_vs_opp} total={oppDisplay || 5} />
        </div>
      </div>
      <div className="shrink-0 w-14">
        <div className="flex justify-between font-mono text-[10px] mb-0.5">
          <span className="font-bold text-accent">+{(bet.edge * 100).toFixed(1)}%</span>
          <span className="text-muted-foreground">{(bet.model_p * 100).toFixed(0)}%</span>
        </div>
        <div className="h-0.5 w-full bg-ink/5">
          <div className="h-full bg-accent" style={{ width: `${Math.min(bet.edge * 300, 100)}%` }} />
        </div>
      </div>
      <div className="shrink-0 text-right">
        <div className="font-mono font-bold">{bet.sb_odds.toFixed(2)}</div>
        <div className="font-mono text-[9px] text-muted-foreground">K {(bet.kelly * 100).toFixed(1)}%</div>
      </div>
    </div>
  );
}

function ValuePanel({ bets, loading }: { bets: APIValueBet[] | undefined; loading: boolean }) {
  const [teamFilter, setTeamFilter] = useState<string | null>(null);
  const [showAllValue, setShowAllValue] = useState(false);

  const teams = useMemo(() => {
    if (!bets) return [];
    return [...new Set(bets.map((b) => b.team))].sort();
  }, [bets]);

  const filtered = useMemo(() => {
    if (!bets) return [];
    return teamFilter ? bets.filter((b) => b.team === teamFilter) : bets;
  }, [bets, teamFilter]);

  const locks  = filtered.filter((b) => b.tier === "lock");
  const strong = filtered.filter((b) => b.tier === "strong");
  const value  = filtered.filter((b) => b.tier === "value");
  const visibleValue = showAllValue ? value : value.slice(0, 6);

  return (
    <div className="space-y-4">
      <SectionHeading title="Best Lines" meta="One line per player" />
      {teams.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          <button
            onClick={() => setTeamFilter(null)}
            className={`px-2 py-1 font-mono text-[10px] font-bold uppercase border transition-colors ${
              teamFilter === null ? "border-ink bg-ink text-paper" : "border-border text-muted-foreground hover:border-ink hover:text-ink"
            }`}
          >
            All teams
          </button>
          {teams.map((t) => (
            <button
              key={t}
              onClick={() => setTeamFilter(t === teamFilter ? null : t)}
              className={`px-2 py-1 font-mono text-[10px] font-bold uppercase border transition-colors ${
                teamFilter === t ? "border-ink bg-ink text-paper" : "border-border text-muted-foreground hover:border-ink hover:text-ink"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      )}
      {loading && <ApiLoading label="Pricing all player lines…" />}
      {locks.length > 0 && (
        <div className="border border-border bg-card">
          <div className="border-b border-border bg-ink/5 px-3 py-2 flex items-center gap-2">
            <span className="bg-ink text-paper px-1.5 py-0.5 font-mono text-[9px] font-bold">LOCK</span>
            <span className="text-[11px] font-bold uppercase tracking-wider">Hit every game — last 5 & vs opponent</span>
          </div>
          {locks.map((b) => <ValueRow key={`${b.player}-${b.stat}-${b.milestone}`} bet={b} />)}
        </div>
      )}
      {strong.length > 0 && (
        <div className="border border-border bg-card">
          <div className="border-b border-border bg-ink/5 px-3 py-2 flex items-center gap-2">
            <span className="bg-ink/15 text-ink px-1.5 py-0.5 font-mono text-[9px] font-bold">STRONG</span>
            <span className="text-[11px] font-bold uppercase tracking-wider">High consistency — 4+ of last 5</span>
          </div>
          {strong.map((b) => <ValueRow key={`${b.player}-${b.stat}-${b.milestone}`} bet={b} />)}
        </div>
      )}
      {visibleValue.length > 0 && (
        <div className="border border-border bg-card">
          <div className="border-b border-border bg-ink/5 px-3 py-2 flex items-center gap-2">
            <span className="border border-border text-muted-foreground px-1.5 py-0.5 font-mono text-[9px] font-bold">VALUE</span>
            <span className="text-[11px] font-bold uppercase tracking-wider">Model edge — lower consistency</span>
          </div>
          {visibleValue.map((b) => <ValueRow key={`${b.player}-${b.stat}-${b.milestone}`} bet={b} />)}
          {value.length > 6 && (
            <button
              onClick={() => setShowAllValue(!showAllValue)}
              className="w-full border-t border-dashed border-border py-2.5 font-mono text-[11px] font-bold uppercase text-muted-foreground hover:text-ink transition-colors"
            >
              {showAllValue ? "Show fewer" : `Show all ${value.length} value lines`}
            </button>
          )}
        </div>
      )}
      {bets?.length === 0 && !loading && (
        <div className="border border-border p-4 text-xs text-muted-foreground">
          No lines with ≥3% edge found right now.
        </div>
      )}
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

function Index() {
  const { data: events, isLoading: evLoading, isError: evError } = useEvents();
  const { data: valueBets, isLoading: valLoading } = useValueBets(0.03);
  const { data: historicalRounds } = useHistoricalRounds();
  const liveGames = useLiveGames().data?.games ?? [];
  const refreshLive = useLiveRefresh();
  const refreshedRef = useRef(false);
  useEffect(() => {
    if (refreshedRef.current) return;
    refreshedRef.current = true;
    refreshLive.mutate();
  }, []);

  const [selectedRound, setSelectedRound] = useState<{ season: number; round: string } | null>(null);

  const roundList = useMemo(
    () => (historicalRounds ? buildRoundList(historicalRounds) : []),
    [historicalRounds],
  );

  const { data: historicalGames, isLoading: histLoading } = useHistoricalRound(
    selectedRound?.season ?? null,
    selectedRound?.round ?? null,
  );

  const isCurrentRound = selectedRound === null;
  const selectedEntry = selectedRound
    ? roundList.find((r) => r.season === selectedRound.season && r.round === selectedRound.round)
    : null;

  return (
    <PageShell>
      {evError && !evLoading && <div className="mb-4"><ApiOfflineBanner /></div>}

      <div className="grid grid-cols-12 gap-6">
        {/* LEFT — Fixtures */}
        <section className="animate-reveal col-span-12 space-y-4 lg:col-span-4">
          {/* Round navigator */}
          {roundList.length > 0 && (
            <RoundNav rounds={roundList} selected={selectedRound} onSelect={setSelectedRound} />
          )}

          {isCurrentRound ? (
            <>
              <SectionHeading title="This Round" meta="Click a game for all props" />
              {evLoading && <ApiLoading label="Loading fixtures…" />}
              {events?.map((ev) => <GameCard key={ev.id} ev={ev} liveGames={liveGames} />)}
              {events?.length === 0 && (
                <div className="border border-border p-4 text-xs text-muted-foreground">
                  No upcoming games found. Check back closer to game day or start the API server.
                </div>
              )}
            </>
          ) : selectedEntry?.hasData ? (
            <>
              <SectionHeading
                title={`${selectedRound!.season} · ${roundLabel(selectedRound!.round)}`}
                meta={selectedEntry.date ?? ""}
              />
              {histLoading && <ApiLoading label="Loading round results…" />}
              {historicalGames?.map((g) => (
                <HistoricalGameCard key={`${g.home}-${g.away}-${g.date}`} game={g} liveGames={liveGames} />
              ))}
              {!histLoading && !historicalGames?.length && (
                <div className="border border-border p-4 text-xs text-muted-foreground">
                  No game data found for this round.
                </div>
              )}
            </>
          ) : (
            <>
              <SectionHeading
                title={`${selectedRound!.season} · ${roundLabel(selectedRound!.round)}`}
                meta="Upcoming"
              />
              <div className="border border-border bg-card p-6 text-center space-y-1">
                <div className="font-mono text-[11px] font-bold uppercase text-muted-foreground">Odds not yet published</div>
                <div className="font-mono text-[10px] text-muted-foreground">
                  Matchups and odds will appear here closer to game day.
                </div>
              </div>
            </>
          )}
        </section>

        {/* CENTRE — Value bets (always current round) */}
        <section className="animate-reveal col-span-12 [animation-delay:150ms] lg:col-span-5">
          <ValuePanel bets={valueBets} loading={valLoading} />
        </section>

        {/* RIGHT — Ladder + Insights */}
        <section className="animate-reveal col-span-12 space-y-5 [animation-delay:300ms] lg:col-span-3">
          <SectionHeading title="Ladder" meta="2026 · Round 16" />
          <LadderTable snapshot />
          <SectionHeading title="Form Index" meta="Stadium · Weather" />
          {INSIGHTS.slice(0, 2).map((i) => <InsightCard key={i.tag} i={i} />)}
        </section>
      </div>
    </PageShell>
  );
}
