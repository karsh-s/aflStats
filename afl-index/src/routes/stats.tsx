import { createFileRoute } from "@tanstack/react-router";
import { useState, useMemo } from "react";
import { PageShell, SectionHeading } from "@/components/page-shell";
import { PLAYER_STATS, TEAM_STATS, TEAM_NAMES, TEAM_COLORS, type TeamCode } from "@/lib/afl-data";
import { usePlayerStats, useTeamStats } from "@/lib/queries";

export const Route = createFileRoute("/stats")({
  head: () => ({
    meta: [
      { title: "Stats Leaders · AFL.Index" },
      {
        name: "description",
        content:
          "AFL 2026 season statistics leaders — disposals, kicks, marks, goals, behinds, tackles and more by player and team.",
      },
    ],
  }),
  component: StatsPage,
});

type StatKey = "di" | "ki" | "mk" | "hb" | "gl" | "bh" | "ho" | "tk" | "rb" | "if_" | "cl" | "cp";
type StatAvgKey = "diAvg" | "kiAvg" | "mkAvg" | "hbAvg" | "glAvg" | "bhAvg" | "hoAvg" | "tkAvg" | "rbAvg" | "ifAvg" | "clAvg" | "cpAvg";

interface StatConfig {
  key: StatKey;
  avgKey: StatAvgKey;
  label: string;
  short: string;
}

const STAT_CONFIGS: StatConfig[] = [
  { key: "di", avgKey: "diAvg", label: "Disposals", short: "DI" },
  { key: "ki", avgKey: "kiAvg", label: "Kicks", short: "KI" },
  { key: "mk", avgKey: "mkAvg", label: "Marks", short: "MK" },
  { key: "hb", avgKey: "hbAvg", label: "Handballs", short: "HB" },
  { key: "gl", avgKey: "glAvg", label: "Goals", short: "GL" },
  { key: "bh", avgKey: "bhAvg", label: "Behinds", short: "BH" },
  { key: "ho", avgKey: "hoAvg", label: "Hitouts", short: "HO" },
  { key: "tk", avgKey: "tkAvg", label: "Tackles", short: "TK" },
  { key: "rb", avgKey: "rbAvg", label: "Rebound 50s", short: "R50" },
  { key: "if_", avgKey: "ifAvg", label: "Inside 50s", short: "I50" },
  { key: "cl", avgKey: "clAvg", label: "Clearances", short: "CL" },
  { key: "cp", avgKey: "cpAvg", label: "Contested Poss.", short: "CP" },
];

function PlayerLeaders() {
  const [activeStat, setActiveStat] = useState<StatConfig>(STAT_CONFIGS[0]);
  const [sortBy, setSortBy] = useState<"total" | "avg">("total");
  const [minGames, setMinGames] = useState(5);
  const { data: livePlayers } = usePlayerStats(1);
  const playerRows = (livePlayers && livePlayers.length
    ? (livePlayers as unknown as typeof PLAYER_STATS)
    : PLAYER_STATS);

  const sorted = useMemo(() => {
    return [...playerRows]
      .filter((p) => p.gm >= minGames)
      .sort((a, b) =>
        sortBy === "total"
          ? (b[activeStat.key] as number) - (a[activeStat.key] as number)
          : (b[activeStat.avgKey] as number) - (a[activeStat.avgKey] as number),
      )
      .slice(0, 50);
  }, [playerRows, activeStat, sortBy, minGames]);

  const maxVal = sorted.length > 0 ? (sorted[0][sortBy === "total" ? activeStat.key : activeStat.avgKey] as number) : 1;

  return (
    <div className="space-y-5">
      {/* Stat selector */}
      <div className="flex flex-wrap gap-1.5">
        {STAT_CONFIGS.map((s) => (
          <button
            key={s.key}
            onClick={() => setActiveStat(s)}
            className={`border px-3 py-1 font-mono text-[11px] font-bold uppercase transition-colors ${
              activeStat.key === s.key
                ? "border-ink bg-ink text-paper"
                : "border-border text-muted-foreground hover:border-ink hover:text-ink"
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-4 border-b border-dashed border-border pb-3">
        <div className="flex gap-2">
          {(["total", "avg"] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => setSortBy(mode)}
              className={`px-3 py-1 text-[11px] font-bold uppercase transition-colors ${
                sortBy === mode
                  ? "bg-accent text-white"
                  : "text-muted-foreground hover:text-ink"
              }`}
            >
              {mode === "total" ? "Season Total" : "Per Game Avg"}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2 text-[11px] text-muted-foreground">
          <span className="font-bold uppercase">Min games:</span>
          {[1, 5, 8, 10].map((n) => (
            <button
              key={n}
              onClick={() => setMinGames(n)}
              className={`w-8 py-0.5 text-center font-mono transition-colors ${
                minGames === n ? "bg-ink text-paper" : "hover:text-ink"
              }`}
            >
              {n}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b-2 border-ink text-[10px] font-bold uppercase text-muted-foreground">
              <th className="w-8 pb-2 pr-3 font-mono">#</th>
              <th className="pb-2 pr-4">Player</th>
              <th className="pb-2 pr-4">Team</th>
              <th className="pb-2 pr-4 text-right font-mono">GM</th>
              <th className="pb-2 pr-4 text-right">{activeStat.short} Total</th>
              <th className="pb-2 pr-4 text-right">{activeStat.short} Avg</th>
              <th className="pb-2 w-40">Distribution</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((p, i) => {
              const val = sortBy === "total" ? (p[activeStat.key] as number) : (p[activeStat.avgKey] as number);
              const barWidth = maxVal > 0 ? (val / maxVal) * 100 : 0;
              const inTop8 = i < 8;
              return (
                <tr
                  key={p.player + p.team}
                  className={`border-b border-border transition-colors hover:bg-card ${
                    i === 0 ? "bg-ink text-paper hover:bg-ink/90" : ""
                  }`}
                >
                  <td className="py-2 pr-3 font-mono text-xs text-muted-foreground">
                    {i + 1}
                  </td>
                  <td className="py-2 pr-4 font-bold">{p.player}</td>
                  <td className="py-2 pr-4">
                    <span className="flex items-center gap-1.5">
                      <span
                        className="size-2 shrink-0 rounded-full"
                        style={{ background: TEAM_COLORS[p.team] }}
                      />
                      <span className={`font-mono text-xs ${i === 0 ? "text-paper/70" : "text-muted-foreground"}`}>
                        {p.team}
                      </span>
                    </span>
                  </td>
                  <td className="py-2 pr-4 text-right font-mono text-xs">{p.gm}</td>
                  <td className={`py-2 pr-4 text-right font-mono font-bold ${inTop8 && i !== 0 ? "text-ink" : ""}`}>
                    {p[activeStat.key]}
                  </td>
                  <td className={`py-2 pr-4 text-right font-mono text-sm ${i === 0 ? "text-accent" : "text-accent"}`}>
                    {(p[activeStat.avgKey] as number).toFixed(1)}
                  </td>
                  <td className="py-2">
                    <div className={`h-1.5 w-full ${i === 0 ? "bg-paper/20" : "bg-ink/5"}`}>
                      <div
                        className={`h-full ${i === 0 ? "bg-paper" : "bg-ink"}`}
                        style={{ width: `${barWidth}%` }}
                      />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TeamLeaders() {
  const { data: liveTeams } = useTeamStats();
  const teamRows = (liveTeams && liveTeams.length
    ? (liveTeams as unknown as typeof TEAM_STATS)
    : TEAM_STATS);
  const [sortKey, setSortKey] = useState<keyof typeof TEAM_STATS[0]>("forAvg");

  const sorted = useMemo(
    () =>
      [...teamRows].sort((a, b) => {
        const av = a[sortKey] as number;
        const bv = b[sortKey] as number;
        // For "against" stats, lower is better so sort ascending
        return sortKey === "againstAvg" || sortKey === "against"
          ? av - bv
          : bv - av;
      }),
    [teamRows, sortKey],
  );

  type ColConfig = { key: keyof typeof TEAM_STATS[0]; label: string; suffix?: string };
  const cols: ColConfig[] = [
    { key: "played", label: "Played" },
    { key: "for", label: "Pts For" },
    { key: "against", label: "Pts Agn" },
    { key: "forAvg", label: "For/Gm", suffix: "" },
    { key: "againstAvg", label: "Agn/Gm", suffix: "" },
    { key: "pct", label: "%", suffix: "" },
    { key: "points", label: "Ladder Pts" },
  ];

  const maxFor = Math.max(...teamRows.map((t) => t.forAvg));
  const maxAgainst = Math.max(...teamRows.map((t) => t.againstAvg));

  return (
    <div className="space-y-4">
      <p className="text-[11px] text-muted-foreground">
        Click any column header to sort. 2026 Season — Round 15.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b-2 border-ink text-[10px] font-bold uppercase">
              <th className="pb-2 pr-4 w-8">#</th>
              <th className="pb-2 pr-6">Team</th>
              {cols.map((c) => (
                <th
                  key={String(c.key)}
                  className={`pb-2 px-3 text-right cursor-pointer select-none transition-colors hover:text-ink ${
                    sortKey === c.key ? "text-ink" : "text-muted-foreground"
                  }`}
                  onClick={() => setSortKey(c.key)}
                >
                  {c.label}
                  {sortKey === c.key && <span className="ml-1">↓</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((t, i) => (
              <tr
                key={t.team}
                className={`border-b border-border transition-colors hover:bg-card ${
                  i === 0 ? "bg-ink text-paper" : ""
                }`}
              >
                <td className="py-2.5 pr-4 font-mono text-xs text-muted-foreground">{i + 1}</td>
                <td className="py-2.5 pr-6">
                  <span className="flex items-center gap-2">
                    <span
                      className="size-2.5 shrink-0 rounded-full"
                      style={{ background: TEAM_COLORS[t.team] }}
                    />
                    <span className="font-bold">{TEAM_NAMES[t.team]}</span>
                  </span>
                </td>
                <td className="py-2.5 px-3 text-right font-mono text-sm">{t.played}</td>
                <td className="py-2.5 px-3 text-right font-mono text-sm">{t.for}</td>
                <td className="py-2.5 px-3 text-right font-mono text-sm">{t.against}</td>
                <td className="py-2.5 px-3 text-right font-mono font-bold">
                  <span className={i === 0 ? "text-accent" : "text-accent"}>
                    {t.forAvg.toFixed(1)}
                  </span>
                  <div className="mt-0.5 h-0.5 w-full bg-ink/5">
                    <div
                      className={`h-full ${i === 0 ? "bg-paper" : "bg-accent"}`}
                      style={{ width: `${(t.forAvg / maxFor) * 100}%` }}
                    />
                  </div>
                </td>
                <td className="py-2.5 px-3 text-right font-mono font-bold">
                  <span className="text-muted-foreground">{t.againstAvg.toFixed(1)}</span>
                  <div className="mt-0.5 h-0.5 w-full bg-ink/5">
                    <div
                      className="h-full bg-ink/30"
                      style={{ width: `${(t.againstAvg / maxAgainst) * 100}%` }}
                    />
                  </div>
                </td>
                <td className="py-2.5 px-3 text-right font-mono text-sm">{t.pct.toFixed(1)}</td>
                <td className="py-2.5 px-3 text-right font-mono font-bold">{t.points}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StatsPage() {
  const [tab, setTab] = useState<"player" | "team">("player");

  return (
    <PageShell>
      <div className="space-y-6">
        <div className="flex items-end justify-between border-b-2 border-ink pb-1">
          <h2 className="font-display text-2xl font-extrabold uppercase tracking-tighter">
            Season Stats Leaders
          </h2>
          <span className="mb-1 font-mono text-[10px] text-muted-foreground">
            2026 · AFL Tables
          </span>
        </div>

        {/* Tab bar */}
        <div className="flex gap-0 border-b border-border">
          {(["player", "team"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`border-b-2 px-6 py-2.5 text-[11px] font-bold uppercase tracking-widest transition-colors ${
                tab === t
                  ? "-mb-px border-ink text-ink"
                  : "border-transparent text-muted-foreground hover:text-ink"
              }`}
            >
              {t === "player" ? "Player Leaders" : "By Team"}
            </button>
          ))}
        </div>

        {tab === "player" ? <PlayerLeaders /> : <TeamLeaders />}
      </div>
    </PageShell>
  );
}
