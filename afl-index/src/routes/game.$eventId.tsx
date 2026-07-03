import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, useMemo } from "react";
import { PageShell, SectionHeading } from "@/components/page-shell";
import { ApiLoading } from "@/components/api-status";
import { useEvents, useGameProps, useGameBestLines } from "@/lib/queries";
import { TEAM_COLORS, TEAM_NAMES, type TeamCode } from "@/lib/afl-data";
import type { APIProp } from "@/lib/api";
import type { APIBestLine } from "@/lib/queries";

export const Route = createFileRoute("/game/$eventId")({
  component: GamePage,
});

// ── Reverse lookup: team name → code ──────────────────────────────────────
// Includes both TEAM_NAMES values and common AFL Tables / Odds API short-forms.

const _fromName: Record<string, TeamCode> = Object.fromEntries(
  Object.entries(TEAM_NAMES).map(([code, name]) => [name, code as TeamCode]),
);

// Extra aliases for names the API returns that differ from TEAM_NAMES
const _extraAliases: Record<string, TeamCode> = {
  "GWS": "GWS",
  "Gold Coast Suns": "GCS",
  "North Melbourne": "NTH",
  "St Kilda": "STK",
  "Western Bulldogs": "WBD",
  "Brisbane Lions": "BRL",
  "Greater Western Sydney": "GWS",
};

const codeFromName = { ..._fromName, ..._extraAliases };

function teamColor(teamName: string): string {
  const code = codeFromName[teamName];
  return code ? TEAM_COLORS[code] : "#888";
}

// ── Stat config ────────────────────────────────────────────────────────────

const STATS = ["disposals", "goals", "marks", "tackles"] as const;
type Stat = (typeof STATS)[number];

const STAT_LABEL: Record<Stat, string> = {
  disposals: "Disposals",
  goals: "Goals",
  marks: "Marks",
  tackles: "Tackles",
};

// ── Helpers ────────────────────────────────────────────────────────────────

function edgeColor(edge: number | null): string {
  if (edge == null) return "text-muted-foreground";
  if (edge >= 0.08) return "text-accent font-bold";
  if (edge >= 0.04) return "text-accent";
  return "text-muted-foreground";
}

function GradientCell({ p }: { p: number }) {
  const pct = Math.round(p * 100);
  const r = p >= 0.5 ? Math.round(220 - 110 * ((p - 0.5) / 0.5)) : 220;
  const g = p < 0.5 ? Math.round(80 + 120 * (p / 0.5)) : 200;
  const bg = `rgba(${r},${g},90,0.45)`;
  return (
    <td className="py-1.5 px-2 text-right font-mono text-xs" style={{ background: bg }}>
      {pct}%
    </td>
  );
}

function HitDots({ rate, total }: { rate: number | null; total: number }) {
  if (rate === null || total === 0)
    return <span className="font-mono text-[9px] text-muted-foreground/30">—</span>;
  const filled = Math.round(rate * total);
  return (
    <span className="flex gap-0.5 items-center">
      {Array.from({ length: total }).map((_, i) => (
        <span
          key={i}
          className={`inline-block size-1.5 rounded-full ${i < filled ? "bg-ink" : "bg-ink/15"}`}
        />
      ))}
    </span>
  );
}

// ── Player ladder (one stat, all milestones) ───────────────────────────────

function PlayerLadder({
  props,
  stat,
  homeTeam,
  awayTeam,
}: {
  props: APIProp[];
  stat: Stat;
  homeTeam: string;
  awayTeam: string;
}) {
  const filtered = props.filter((p) => p.stat === stat);
  const players = [...new Set(filtered.map((p) => p.player))].sort();
  const milestones = [...new Set(filtered.map((p) => p.milestone))].sort(
    (a, b) => parseInt(a) - parseInt(b),
  );

  const [view, setView] = useState<"prob" | "odds" | "edge">("prob");
  const [playerFilter, setPlayerFilter] = useState("");

  const filteredPlayers = players.filter((p) =>
    p.toLowerCase().includes(playerFilter.toLowerCase()),
  );

  const lookup: Record<string, APIProp> = {};
  filtered.forEach((p) => {
    lookup[`${p.player}|${p.milestone}`] = p;
  });

  // Find each player's team for color dots
  const playerTeam: Record<string, string> = {};
  filtered.forEach((p) => {
    playerTeam[p.player] = p.team;
  });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-1">
          {(["prob", "odds", "edge"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`px-3 py-1 font-mono text-[11px] font-bold uppercase transition-colors border ${
                view === v
                  ? "border-ink bg-ink text-paper"
                  : "border-border text-muted-foreground hover:text-ink"
              }`}
            >
              {v === "prob" ? "Model %" : v === "odds" ? "SB Odds" : "Edge"}
            </button>
          ))}
        </div>
        <input
          type="text"
          placeholder="Filter players…"
          value={playerFilter}
          onChange={(e) => setPlayerFilter(e.target.value)}
          className="ml-auto border border-border bg-card px-3 py-1 font-mono text-[11px] outline-none focus:border-ink"
        />
      </div>

      {view === "prob" && (
        <div className="flex gap-4 text-[10px] text-muted-foreground">
          <span className="flex items-center gap-1">
            <span className="inline-block size-3" style={{ background: "rgba(110,200,90,0.45)" }} />
            ≥72% likely
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block size-3" style={{ background: "rgba(220,200,90,0.45)" }} />
            50–71%
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block size-3" style={{ background: "rgba(220,80,90,0.45)" }} />
            &lt;50%
          </span>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b-2 border-ink">
              <th className="py-2 pr-4 font-mono text-[10px] font-bold uppercase text-muted-foreground sticky left-0 bg-paper">
                Player
              </th>
              <th className="py-2 pr-4 font-mono text-[10px] font-bold uppercase text-muted-foreground">
                Proj
              </th>
              {milestones.map((m) => (
                <th
                  key={m}
                  className="px-2 py-2 text-right font-mono text-[10px] font-bold uppercase text-muted-foreground"
                >
                  {m}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filteredPlayers.map((player, i) => {
              const firstRow = filtered.find((p) => p.player === player);
              const pTeam = playerTeam[player] ?? "";
              const pColor = pTeam === homeTeam
                ? teamColor(homeTeam)
                : pTeam === awayTeam
                ? teamColor(awayTeam)
                : "#888";
              return (
                <tr
                  key={player}
                  className={`border-b border-border hover:bg-ink/3 ${i % 2 === 0 ? "" : "bg-ink/[0.015]"}`}
                >
                  <td className="py-1.5 pr-4 sticky left-0 bg-inherit">
                    <div className="flex items-center gap-1.5">
                      <span
                        className="shrink-0 size-2 rounded-full"
                        style={{ background: pColor }}
                      />
                      <span className="font-bold">{player}</span>
                    </div>
                  </td>
                  <td className="py-1.5 pr-4 font-mono text-muted-foreground">
                    {firstRow?.proj?.toFixed(1) ?? "—"}
                  </td>
                  {milestones.map((m) => {
                    const cell = lookup[`${player}|${m}`];
                    if (!cell)
                      return (
                        <td key={m} className="px-2 py-1.5 text-center text-muted-foreground/30">
                          ·
                        </td>
                      );

                    if (view === "prob") return <GradientCell key={m} p={cell.model_p} />;

                    if (view === "odds") {
                      return (
                        <td
                          key={m}
                          className={`px-2 py-1.5 text-right font-mono ${cell.sb_odds ? "font-bold" : "text-muted-foreground/40"}`}
                        >
                          {cell.sb_odds ? cell.sb_odds.toFixed(2) : "·"}
                        </td>
                      );
                    }

                    return (
                      <td
                        key={m}
                        className={`px-2 py-1.5 text-right font-mono ${edgeColor(cell.edge)}`}
                      >
                        {cell.edge != null ? `+${(cell.edge * 100).toFixed(1)}%` : "·"}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Best lines panel ───────────────────────────────────────────────────────

const TIER_META: Record<string, { label: string; cls: string }> = {
  lock:   { label: "LOCK",   cls: "bg-ink text-paper" },
  strong: { label: "STRONG", cls: "bg-ink/15 text-ink" },
  value:  { label: "VALUE",  cls: "border border-border text-muted-foreground" },
};

function BestLines({
  lines,
  homeTeam,
  awayTeam,
}: {
  lines: APIBestLine[];
  homeTeam: string;
  awayTeam: string;
}) {
  if (lines.length === 0) {
    return (
      <div className="border border-border p-4 text-xs text-muted-foreground">
        No lines found (model P ≥ 45%). Either no data loaded yet or no markets available.
      </div>
    );
  }

  return (
    <div className="border border-border bg-card">
      <div className="border-b border-border bg-ink/5 px-3 py-2 flex items-center justify-between">
        <span className="text-[11px] font-bold uppercase tracking-wider">
          Best Lines — One per player · Sorted by consistency
        </span>
        <span className="font-mono text-[9px] text-muted-foreground">
          {lines.length} lines across all stats
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-border text-[10px] font-bold uppercase text-muted-foreground">
              <th className="p-3">Player</th>
              <th className="p-3">Stat · Line</th>
              <th className="p-3">L5 / L10</th>
              <th className="p-3">Vs Opp</th>
              <th className="p-3 text-right">Model P</th>
              <th className="p-3 text-right">SB Odds</th>
              <th className="p-3 text-right">Edge</th>
            </tr>
          </thead>
          <tbody className="text-xs">
            {lines.map((line) => {
              const tm = TIER_META[line.tier] ?? TIER_META.value;
              const pColor =
                line.team === homeTeam
                  ? teamColor(homeTeam)
                  : line.team === awayTeam
                  ? teamColor(awayTeam)
                  : "#888";
              const oppDisplay = Math.min(line.opp_n || 5, 5);
              return (
                <tr
                  key={`${line.player}-${line.stat}`}
                  className="border-b border-border last:border-0 hover:bg-accent/5"
                >
                  <td className="p-3">
                    <div className="flex items-center gap-1.5">
                      <span
                        className="shrink-0 size-2 rounded-full"
                        style={{ background: pColor }}
                      />
                      <div>
                        <div className="font-bold">{line.player}</div>
                        <div className="font-mono text-[9px] text-muted-foreground">
                          {line.team}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="p-3">
                    <span
                      className={`mr-1.5 px-1.5 py-0.5 font-mono text-[9px] font-bold ${tm.cls}`}
                    >
                      {tm.label}
                    </span>
                    <span className="capitalize text-muted-foreground">{line.stat}</span>{" "}
                    <span className="font-bold text-ink">{line.milestone}</span>
                  </td>
                  <td className="p-3">
                    <div className="space-y-0.5">
                      <div className="flex items-center gap-1">
                        <span className="font-mono text-[8px] text-muted-foreground w-4">L5</span>
                        <HitDots rate={line.hit_last_5} total={5} />
                      </div>
                      {line.hit_last_10 !== null && (
                        <div className="flex items-center gap-1">
                          <span className="font-mono text-[8px] text-muted-foreground w-4">L10</span>
                          <HitDots rate={line.hit_last_10} total={10} />
                        </div>
                      )}
                    </div>
                  </td>
                  <td className="p-3">
                    <HitDots rate={line.hit_vs_opp} total={oppDisplay} />
                  </td>
                  <td className="p-3 text-right font-mono">
                    {(line.model_p * 100).toFixed(0)}%
                  </td>
                  <td className="p-3 text-right font-mono font-bold">
                    {line.sb_odds ? line.sb_odds.toFixed(2) : "—"}
                  </td>
                  <td className={`p-3 text-right font-mono ${edgeColor(line.edge)}`}>
                    {line.edge != null ? `+${(line.edge * 100).toFixed(1)}%` : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="border-t border-dashed border-border px-4 py-2.5 text-[10px] text-muted-foreground">
        Showing lines with SB odds, ≥2% edge, and consistency: hit 5/5 last 5, OR 8+/10 last 10, OR 5/5 vs this opponent.
        One line per player per stat · sorted by edge.
      </div>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

function GamePage() {
  const { eventId } = Route.useParams();
  const { data: events } = useEvents();
  const { data: props, isLoading: propsLoading } = useGameProps(eventId);
  const { data: bestLines, isLoading: bestLinesLoading } = useGameBestLines(eventId);

  const [activeStat, setActiveStat] = useState<Stat>("disposals");
  const [teamFilter, setTeamFilter] = useState<"home" | "away" | null>(null);

  const ev = events?.find((e) => e.id === eventId);
  const homeWins = (ev?.p_home ?? 0.5) >= 0.5;

  const homeColor = ev ? teamColor(ev.home) : "#1a1a1a";
  const awayColor = ev ? teamColor(ev.away) : "#888";

  const filteredProps = useMemo(() => {
    if (!props || !teamFilter || !ev) return props ?? [];
    const name = teamFilter === "home" ? ev.home : ev.away;
    return props.filter((p) => p.team === name);
  }, [props, teamFilter, ev]);

  const filteredBestLines = useMemo(() => {
    if (!bestLines || !teamFilter || !ev) return bestLines ?? [];
    const name = teamFilter === "home" ? ev.home : ev.away;
    return bestLines.filter((l) => l.team === name);
  }, [bestLines, teamFilter, ev]);

  const isLoading = propsLoading || bestLinesLoading;

  return (
    <PageShell>
      <div className="space-y-6">
        {/* Header */}
        <div>
          <Link
            to="/"
            className="font-mono text-[10px] text-muted-foreground hover:text-ink transition-colors"
          >
            ← All games
          </Link>
          <div className="mt-3 flex items-end justify-between border-b-2 border-ink pb-1">
            <h2 className="font-display text-2xl font-extrabold uppercase tracking-tighter">
              {ev ? `${ev.home} v ${ev.away}` : "Game Props"}
            </h2>
            {ev && (
              <span className="mb-1 font-mono text-[10px] text-muted-foreground">
                {ev.venue} · {ev.slot}
              </span>
            )}
          </div>
        </div>

        {/* Win probability bar */}
        {ev && (
          <div className="border border-border bg-card p-4">
            <div className="mb-3 flex justify-between text-[10px] font-bold uppercase text-muted-foreground">
              <span>Win probability</span>
              <span className="text-accent">Model pick: {ev.pick}</span>
            </div>
            <div className="mb-2 flex items-center gap-3">
              <div className="flex items-center gap-1.5 w-36">
                <span
                  className="size-2.5 shrink-0 rounded-full"
                  style={{ background: homeColor }}
                />
                <span
                  className={`truncate text-sm font-bold ${homeWins ? "text-ink" : "text-muted-foreground"}`}
                >
                  {ev.home}
                </span>
              </div>
              <div className="flex-1 flex h-5 overflow-hidden bg-ink/5">
                <div
                  className="h-full flex items-center justify-end pr-2"
                  style={{ width: `${ev.p_home * 100}%`, background: homeColor }}
                >
                  <span className="font-mono text-[10px] font-bold text-paper">
                    {(ev.p_home * 100).toFixed(0)}%
                  </span>
                </div>
                <div
                  className="h-full flex items-center pl-2"
                  style={{ width: `${ev.p_away * 100}%`, background: awayColor, opacity: 0.7 }}
                >
                  <span className="font-mono text-[10px] font-bold text-paper">
                    {(ev.p_away * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-1.5 w-36 justify-end">
                <span
                  className={`truncate text-right text-sm font-bold ${!homeWins ? "text-ink" : "text-muted-foreground"}`}
                >
                  {ev.away}
                </span>
                <span
                  className="size-2.5 shrink-0 rounded-full"
                  style={{ background: awayColor }}
                />
              </div>
            </div>
            <div className="flex flex-wrap gap-4 text-[10px] text-muted-foreground mt-1">
              {ev.rain_mm != null && ev.rain_mm >= 1 && (
                <span>Rain: {ev.rain_mm.toFixed(0)}mm</span>
              )}
              {ev.wind_kmh != null && ev.wind_kmh >= 20 && (
                <span>Wind: {ev.wind_kmh.toFixed(0)}km/h</span>
              )}
              {ev.h2h !== "—" && <span>H2H (last 10): {ev.h2h}</span>}
            </div>

            {/* Team filter */}
            <div className="mt-3 flex gap-2 border-t border-dashed border-border pt-3">
              <span className="font-mono text-[10px] text-muted-foreground self-center">Filter:</span>
              <button
                onClick={() => setTeamFilter(null)}
                className={`px-2.5 py-1 font-mono text-[10px] font-bold uppercase border transition-colors ${
                  teamFilter === null
                    ? "border-ink bg-ink text-paper"
                    : "border-border text-muted-foreground hover:border-ink hover:text-ink"
                }`}
              >
                All players
              </button>
              {ev && (
                <>
                  <button
                    onClick={() => setTeamFilter(teamFilter === "home" ? null : "home")}
                    className={`flex items-center gap-1.5 px-2.5 py-1 font-mono text-[10px] font-bold uppercase border transition-colors ${
                      teamFilter === "home"
                        ? "border-ink text-paper"
                        : "border-border text-muted-foreground hover:border-ink hover:text-ink"
                    }`}
                    style={teamFilter === "home" ? { background: homeColor, borderColor: homeColor } : {}}
                  >
                    <span
                      className="size-2 rounded-full shrink-0"
                      style={{ background: teamFilter === "home" ? "white" : homeColor }}
                    />
                    {ev.home}
                  </button>
                  <button
                    onClick={() => setTeamFilter(teamFilter === "away" ? null : "away")}
                    className={`flex items-center gap-1.5 px-2.5 py-1 font-mono text-[10px] font-bold uppercase border transition-colors ${
                      teamFilter === "away"
                        ? "border-ink text-paper"
                        : "border-border text-muted-foreground hover:border-ink hover:text-ink"
                    }`}
                    style={teamFilter === "away" ? { background: awayColor, borderColor: awayColor } : {}}
                  >
                    <span
                      className="size-2 rounded-full shrink-0"
                      style={{ background: teamFilter === "away" ? "white" : awayColor }}
                    />
                    {ev.away}
                  </button>
                </>
              )}
            </div>
          </div>
        )}

        {isLoading && <ApiLoading label="Projecting all player lines…" />}

        {bestLines && (
          <div>
            <SectionHeading
              title="Best Lines to Take"
              meta="Consistency-sorted · All stats"
            />
            <BestLines
              lines={filteredBestLines}
              homeTeam={ev?.home ?? ""}
              awayTeam={ev?.away ?? ""}
            />
          </div>
        )}

        {props && props.length > 0 && (
          <div>
            <SectionHeading title="All Players · All Lines" meta="Click column headers to sort" />

            {/* Stat tabs */}
            <div className="mb-4 flex gap-0 border-b border-border">
              {STATS.map((s) => (
                <button
                  key={s}
                  onClick={() => setActiveStat(s)}
                  className={`border-b-2 px-5 py-2.5 text-[11px] font-bold uppercase tracking-widest transition-colors ${
                    activeStat === s
                      ? "-mb-px border-ink text-ink"
                      : "border-transparent text-muted-foreground hover:text-ink"
                  }`}
                >
                  {STAT_LABEL[s]}
                </button>
              ))}
            </div>

            <PlayerLadder
              props={filteredProps}
              stat={activeStat}
              homeTeam={ev?.home ?? ""}
              awayTeam={ev?.away ?? ""}
            />
          </div>
        )}

        {props?.length === 0 && !isLoading && (
          <div className="border border-border p-6 text-center text-sm text-muted-foreground">
            No player markets available for this game yet. SportsBet typically posts lines 2–3 days
            before the game.
          </div>
        )}
      </div>
    </PageShell>
  );
}
