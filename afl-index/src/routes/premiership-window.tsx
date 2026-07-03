import { createFileRoute } from "@tanstack/react-router";
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  ReferenceArea,
} from "recharts";
import { PageShell } from "@/components/page-shell";
import { TEAM_STATS, TEAM_NAMES, TEAM_COLORS, TEAM_LOGOS, type TeamCode } from "@/lib/afl-data";

export const Route = createFileRoute("/premiership-window")({
  head: () => ({
    meta: [
      { title: "Premiership Window · AFL.Index" },
      {
        name: "description",
        content: "AFL 2026 Premiership Window: scoring rank vs defending rank for every team.",
      },
    ],
  }),
  component: PremiershipWindowPage,
});

// ── Rank computation ───────────────────────────────────────────────────────
// scoringRank 1  = most points scored per game  → should appear RIGHT
// defendingRank 1 = fewest points conceded       → should appear TOP
//
// Transform: x = 19 - scoringRank   → rank 1 → x=18 (RIGHT with domain [0.5,18.5])
//            y = 19 - defendingRank  → rank 1 → y=18 (TOP  with domain [0.5,18.5])

const sortedByFor = [...TEAM_STATS].sort((a, b) => b.forAvg - a.forAvg);
const sortedByAgainst = [...TEAM_STATS].sort((a, b) => a.againstAvg - b.againstAvg);

const scoringRankMap = Object.fromEntries(sortedByFor.map((t, i) => [t.team, i + 1]));
const defendingRankMap = Object.fromEntries(sortedByAgainst.map((t, i) => [t.team, i + 1]));

const chartData = TEAM_STATS.map((t) => ({
  team: t.team,
  x: 19 - scoringRankMap[t.team],    // rank 1 → 18 (right)
  y: 19 - defendingRankMap[t.team],  // rank 1 → 18 (top)
  name: TEAM_NAMES[t.team as TeamCode],
  color: TEAM_COLORS[t.team as TeamCode],
  logo: TEAM_LOGOS[t.team as TeamCode],
  pct: t.pct,
  points: t.points,
  forAvg: t.forAvg,
  againstAvg: t.againstAvg,
  scoringRank: scoringRankMap[t.team],
  defendingRank: defendingRankMap[t.team],
}));

// Window = top 6 in BOTH → transformed x ≥ 13 AND y ≥ 13
const inWindowSet = new Set(
  chartData.filter((d) => d.scoringRank <= 6 && d.defendingRank <= 6).map((d) => d.team),
);

// ── Team crest dot ─────────────────────────────────────────────────────────

function TeamDot(props: {
  cx?: number;
  cy?: number;
  payload?: (typeof chartData)[0];
}) {
  const { cx = 0, cy = 0, payload } = props;
  if (!payload) return null;
  const { team, color, logo } = payload;
  const code = team as TeamCode;
  const inWin = inWindowSet.has(team);
  const r = 26;
  const clipId = `crest-clip-${code}`;

  return (
    <g>
      <defs>
        <clipPath id={clipId}>
          <circle cx={cx} cy={cy} r={r - 1} />
        </clipPath>
      </defs>
      {/* Glow ring for window teams */}
      {inWin && (
        <circle cx={cx} cy={cy} r={r + 6} fill="rgba(34,197,94,0.18)" />
      )}
      {/* Shadow */}
      <circle cx={cx} cy={cy} r={r + 2} fill="rgba(0,0,0,0.18)" />
      {/* White background */}
      <circle
        cx={cx}
        cy={cy}
        r={r}
        fill="white"
        stroke={inWin ? "#16a34a" : "rgba(0,0,0,0.12)"}
        strokeWidth={inWin ? 2.5 : 1}
      />
      {/* Team crest */}
      <image
        href={logo}
        x={cx - r + 1}
        y={cy - r + 1}
        width={(r - 1) * 2}
        height={(r - 1) * 2}
        clipPath={`url(#${clipId})`}
        preserveAspectRatio="xMidYMid meet"
      />
      {/* Fallback color fill (shows if image fails) */}
      <circle cx={cx} cy={cy} r={r} fill={color} opacity={0} style={{ pointerEvents: "none" }} />
    </g>
  );
}

// ── Tooltip ────────────────────────────────────────────────────────────────

function CustomTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: (typeof chartData)[0] }[];
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  const inWin = inWindowSet.has(d.team);
  return (
    <div className="border border-border bg-paper p-3 shadow-lg min-w-[180px]">
      <div className="flex items-center gap-2 border-b border-border pb-2 mb-2">
        <img src={d.logo} alt={d.name} className="size-6 object-contain" />
        <span className="font-bold text-sm">{d.name}</span>
        {inWin && (
          <span className="ml-auto border border-green-700 bg-green-700 px-1.5 py-px font-mono text-[8px] font-bold text-white">
            IN WINDOW
          </span>
        )}
      </div>
      <div className="space-y-1 font-mono text-xs">
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">Scoring rank</span>
          <span className="font-bold text-ink">#{d.scoringRank} / 18</span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">Defending rank</span>
          <span className="font-bold text-ink">#{d.defendingRank} / 18</span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">Pts For / Gm</span>
          <span className="text-ink">{d.forAvg.toFixed(1)}</span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">Pts Agn / Gm</span>
          <span className="text-ink">{d.againstAvg.toFixed(1)}</span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">%</span>
          <span className="font-bold text-accent">{d.pct.toFixed(1)}</span>
        </div>
        <div className="flex justify-between gap-4">
          <span className="text-muted-foreground">Ladder Pts</span>
          <span className="font-bold">{d.points}</span>
        </div>
      </div>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

function PremiershipWindowPage() {
  const inWindow = chartData
    .filter((d) => inWindowSet.has(d.team))
    .sort((a, b) => a.scoringRank + a.defendingRank - (b.scoringRank + b.defendingRank));

  return (
    <PageShell>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-end justify-between border-b-2 border-ink pb-1">
          <h2 className="font-display text-2xl font-extrabold uppercase tracking-tighter">
            Premiership Window
          </h2>
          <span className="mb-1 font-mono text-[10px] text-muted-foreground">
            2026 · After Round 15
          </span>
        </div>

        <p className="max-w-prose text-sm text-muted-foreground">
          Teams in the{" "}
          <span className="font-bold text-ink">top-right quadrant</span>{" "}
          (highlighted green) rank{" "}
          <span className="font-bold text-ink">top 6</span> for both scoring{" "}
          <em>and</em> defending — the{" "}
          <span className="font-bold text-ink">premiership window</span>. Right
          = best scorer, top = fewest conceded. Ranks 1–18, evenly spaced.
        </p>

        {/* Window teams */}
        {inWindow.length > 0 && (
          <div className="flex flex-wrap gap-3">
            {inWindow.map((d) => (
              <div
                key={d.team}
                className="flex items-center gap-2 border border-green-700/30 bg-green-50/50 px-2.5 py-1.5"
              >
                <img src={d.logo} alt={d.name} className="size-5 object-contain" />
                <span className="font-mono text-[10px] font-bold">{d.name}</span>
                <span className="font-mono text-[9px] text-muted-foreground">
                  S#{d.scoringRank} D#{d.defendingRank}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Chart */}
        <div className="border border-border bg-card p-4">
          <div className="relative mb-1 flex justify-between px-[60px] text-[10px] font-bold uppercase text-muted-foreground">
            <span>← Weaker scoring (rank 18)</span>
            <span>Stronger scoring (rank 1) →</span>
          </div>

          <ResponsiveContainer width="100%" height={540}>
            <ScatterChart margin={{ top: 24, right: 80, bottom: 44, left: 20 }}>
              {/* Premiership window highlight — top-right quadrant */}
              <ReferenceArea
                x1={12.5}
                x2={18.5}
                y1={12.5}
                y2={18.5}
                fill="rgba(34,197,94,0.08)"
                stroke="rgba(34,197,94,0.35)"
                strokeDasharray="4 3"
                strokeWidth={1.5}
              />
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.05)" />
              <XAxis
                type="number"
                dataKey="x"
                name="Scoring rank"
                domain={[0.5, 18.5]}
                ticks={[1, 4, 7, 10, 13, 16, 18]}
                tickFormatter={(v) => `#${19 - Math.round(v)}`}
                tick={{ fontSize: 10, fontFamily: "JetBrains Mono, monospace" }}
                label={{
                  value: "Scoring Rank  (rank 1 = most pts/game)",
                  position: "insideBottom",
                  offset: -12,
                  style: {
                    fontSize: 10,
                    fontWeight: "bold",
                    textTransform: "uppercase",
                    fill: "#716969",
                  },
                }}
              />
              <YAxis
                type="number"
                dataKey="y"
                name="Defending rank"
                domain={[0.5, 18.5]}
                ticks={[1, 4, 7, 10, 13, 16, 18]}
                tickFormatter={(v) => `#${19 - Math.round(v)}`}
                tick={{ fontSize: 10, fontFamily: "JetBrains Mono, monospace" }}
                label={{
                  value: "Defending Rank  (rank 1 = fewest conceded)",
                  angle: -90,
                  position: "insideLeft",
                  offset: 12,
                  style: {
                    fontSize: 10,
                    fontWeight: "bold",
                    textTransform: "uppercase",
                    fill: "#716969",
                  },
                }}
              />
              {/* Top-6 boundary */}
              <ReferenceLine
                x={12.5}
                stroke="rgba(34,197,94,0.55)"
                strokeDasharray="6 3"
                strokeWidth={1.5}
                label={{
                  value: "Top 6 →",
                  position: "top",
                  style: {
                    fontSize: 9,
                    fill: "#15803d",
                    fontFamily: "JetBrains Mono, monospace",
                    fontWeight: "bold",
                  },
                }}
              />
              <ReferenceLine
                y={12.5}
                stroke="rgba(34,197,94,0.55)"
                strokeDasharray="6 3"
                strokeWidth={1.5}
                label={{
                  value: "Top 6 ↑",
                  position: "right",
                  style: {
                    fontSize: 9,
                    fill: "#15803d",
                    fontFamily: "JetBrains Mono, monospace",
                    fontWeight: "bold",
                  },
                }}
              />
              <Tooltip content={<CustomTooltip />} />
              <Scatter
                data={chartData}
                shape={(props: Parameters<typeof TeamDot>[0]) => <TeamDot {...props} />}
              />
            </ScatterChart>
          </ResponsiveContainer>

          {/* Quadrant annotations */}
          <div className="mt-2 grid grid-cols-2 gap-3 border-t border-dashed border-border pt-3 text-[10px]">
            <div className="space-y-0.5">
              <div className="font-bold uppercase text-green-700">
                ↗ Top 6 scoring + top 6 defending
              </div>
              <div className="text-muted-foreground">
                Premiership window — attack AND defence firing at elite level
              </div>
            </div>
            <div className="space-y-0.5">
              <div className="font-bold uppercase text-muted-foreground">
                ↘ Top 6 scoring, outside top 6 defending
              </div>
              <div className="text-muted-foreground">
                Entertaining but vulnerable — attack without defence
              </div>
            </div>
            <div className="space-y-0.5">
              <div className="font-bold uppercase text-muted-foreground">
                ↖ Outside top 6 scoring, top 6 defending
              </div>
              <div className="text-muted-foreground">
                Defensive grinders — need forward improvement
              </div>
            </div>
            <div className="space-y-0.5">
              <div className="font-bold uppercase text-muted-foreground">↙ Outside top 6 in both</div>
              <div className="text-muted-foreground">
                Rebuilding — structural improvement needed both ends
              </div>
            </div>
          </div>
        </div>

        {/* Data table */}
        <div className="border border-border bg-card">
          <div className="border-b border-border bg-ink/5 px-4 py-2.5">
            <span className="text-[11px] font-bold uppercase tracking-wider">
              All Teams — Sorted by Combined Rank
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-border text-[10px] font-bold uppercase text-muted-foreground">
                  <th className="p-3">Team</th>
                  <th className="p-3 text-right">Scoring #</th>
                  <th className="p-3 text-right">Defending #</th>
                  <th className="p-3 text-right">For / Gm</th>
                  <th className="p-3 text-right">Agn / Gm</th>
                  <th className="p-3 text-right">%</th>
                  <th className="p-3 text-right">Pts</th>
                  <th className="p-3 text-right">Window</th>
                </tr>
              </thead>
              <tbody>
                {[...chartData]
                  .sort(
                    (a, b) =>
                      a.scoringRank + a.defendingRank - (b.scoringRank + b.defendingRank),
                  )
                  .map((d) => {
                    const inWin = inWindowSet.has(d.team);
                    return (
                      <tr
                        key={d.team}
                        className={`border-b border-border last:border-0 hover:bg-accent/5 ${inWin ? "bg-green-50/40" : ""}`}
                      >
                        <td className="p-3">
                          <span className="flex items-center gap-2">
                            <img
                              src={d.logo}
                              alt={d.name}
                              className="size-6 object-contain"
                            />
                            <span className="font-bold text-sm">{d.name}</span>
                          </span>
                        </td>
                        <td className="p-3 text-right font-mono font-bold text-accent">
                          #{d.scoringRank}
                        </td>
                        <td className="p-3 text-right font-mono font-bold text-accent">
                          #{d.defendingRank}
                        </td>
                        <td className="p-3 text-right font-mono text-sm text-muted-foreground">
                          {d.forAvg.toFixed(1)}
                        </td>
                        <td className="p-3 text-right font-mono text-sm text-muted-foreground">
                          {d.againstAvg.toFixed(1)}
                        </td>
                        <td className="p-3 text-right font-mono text-sm">{d.pct.toFixed(1)}</td>
                        <td className="p-3 text-right font-mono font-bold">{d.points}</td>
                        <td className="p-3 text-right">
                          {inWin ? (
                            <span className="border border-green-700 bg-green-700 px-2 py-0.5 font-mono text-[9px] font-bold uppercase text-white">
                              ✓ In Window
                            </span>
                          ) : (
                            <span className="text-[9px] text-muted-foreground">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </PageShell>
  );
}
