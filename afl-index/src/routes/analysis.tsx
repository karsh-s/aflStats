import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import {
  ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, Label,
} from "recharts";
import { PageShell, SectionHeading } from "@/components/page-shell";
import { ApiLoading } from "@/components/api-status";
import { TEAM_LOGOS, TEAM_CODE_BY_NAME, type TeamCode } from "@/lib/afl-data";
import { useTeamStyles, useStyleMatchups, usePositionConcession, useRoleLeaks } from "@/lib/queries";
import type { TeamStyle, NotableFinding } from "@/lib/api";

export const Route = createFileRoute("/analysis")({
  head: () => ({
    meta: [{ title: "AFL.Index — Tactical Analysis" }],
  }),
  component: Analysis,
});

// ── Constants ────────────────────────────────────────────────────────────────

const STYLE_COLORS: Record<string, string> = {
  "Power":             "#ef4444",
  "Handball Chain":    "#f97316",
  "Kick-Mark":         "#3b82f6",
  "Running / Spread":  "#22c55e",
};

const STYLE_DESCRIPTIONS: Record<string, string> = {
  "Power":            "High contested ball, kick-dominant. Win the contested count and kick long.",
  "Handball Chain":   "High contested possession but handball-heavy. Overload stoppages and move quickly.",
  "Kick-Mark":        "Lower contested, high kick rate. Spread wide and use the corridor.",
  "Running / Spread": "Low contested, handball-movement. Spread the field and create space.",
};

const POS_ORDER = ["Key Defender", "Midfielder", "Ruck", "Forward"];

// ── Helpers ──────────────────────────────────────────────────────────────────

function getLogo(team: string): string | null {
  const code = TEAM_CODE_BY_NAME[team] as TeamCode | undefined;
  return code ? TEAM_LOGOS[code] : null;
}

function dispColor(delta: number): string {
  const v = Math.max(-3, Math.min(3, delta));
  if (v > 2)   return "bg-red-600/80 text-white";
  if (v > 1)   return "bg-red-400/60 text-ink";
  if (v > 0.4) return "bg-red-200/70 text-ink";
  if (v < -2)  return "bg-blue-600/80 text-white";
  if (v < -1)  return "bg-blue-400/60 text-ink";
  if (v < -0.4)return "bg-blue-200/70 text-ink";
  return "bg-transparent text-ink";
}

function goalColor(delta: number): string {
  if (delta > 0.08)  return "bg-red-400/60 text-ink";
  if (delta > 0.03)  return "bg-red-200/70 text-ink";
  if (delta < -0.08) return "bg-blue-400/60 text-ink";
  if (delta < -0.03) return "bg-blue-200/70 text-ink";
  return "bg-transparent text-ink";
}

// ── Custom scatter dot with team logo ────────────────────────────────────────

function TeamDot({ cx, cy, payload }: { cx?: number; cy?: number; payload?: TeamStyle }) {
  if (!payload || cx === undefined || cy === undefined) return null;
  const logo = getLogo(payload.team);
  const color = STYLE_COLORS[payload.style] ?? "#888";
  const SIZE = 18;
  return (
    <g>
      <circle cx={cx} cy={cy} r={SIZE / 2 + 3} fill={color} opacity={0.25} />
      {logo
        ? <image href={logo} x={cx - SIZE / 2} y={cy - SIZE / 2} width={SIZE} height={SIZE} />
        : <circle cx={cx} cy={cy} r={7} fill={color} />
      }
    </g>
  );
}

function ScatterTooltip({ active, payload }: { active?: boolean; payload?: { payload: TeamStyle }[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="border border-ink/10 bg-paper px-3 py-2 text-xs shadow-lg">
      <p className="font-bold">{d.team}</p>
      <p className="text-muted-foreground">{d.style}</p>
      <p>Contested: {(d.contested_ratio * 100).toFixed(1)}%</p>
      <p>Kick ratio: {(d.kick_ratio * 100).toFixed(1)}%</p>
      <p>Clearances: {d.avg_clearances}/g · Tackles: {d.avg_tackles}/g</p>
    </div>
  );
}

// ── Section 1: Team Styles ───────────────────────────────────────────────────

function TeamStylesSection({ styles }: { styles: TeamStyle[] }) {
  const [selected, setSelected] = useState<TeamStyle | null>(null);
  const s = selected ?? styles[0];

  return (
    <div className="space-y-6">
      <SectionHeading title="Team Game Styles" meta="2023–2026 averages" />
      <p className="text-sm text-muted-foreground max-w-2xl">
        Teams are classified along two axes: how contested their football is (contested possession %)
        and how kick-dominant vs handball-reliant they are. This produces four distinct archetypes.
      </p>

      <div className="grid grid-cols-12 gap-6">
        {/* Scatter plot */}
        <div className="col-span-12 lg:col-span-7 h-[420px]">
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ top: 20, right: 30, bottom: 40, left: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-ink)" opacity={0.08} />
              <XAxis
                type="number" dataKey="kick_ratio" name="Kick ratio"
                domain={[0.55, 0.65]} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
                tick={{ fontSize: 10 }} tickCount={6}
              >
                <Label value="Kick ratio →  (more kick-dominant)" offset={-10} position="insideBottom" style={{ fontSize: 10, fill: "var(--color-muted-foreground)" }} />
              </XAxis>
              <YAxis
                type="number" dataKey="contested_ratio" name="Contested"
                domain={[0.34, 0.41]} tickFormatter={(v) => `${(v * 100).toFixed(1)}%`}
                tick={{ fontSize: 10 }} tickCount={5} width={52}
              >
                <Label value="Contested %" angle={-90} position="insideLeft" style={{ fontSize: 10, fill: "var(--color-muted-foreground)" }} />
              </YAxis>
              <ReferenceLine x={0.590} stroke="var(--color-ink)" strokeDasharray="4 4" opacity={0.25} />
              <ReferenceLine y={0.375} stroke="var(--color-ink)" strokeDasharray="4 4" opacity={0.25} />
              <Tooltip content={<ScatterTooltip />} />
              <Scatter
                data={styles}
                shape={(props: { cx?: number; cy?: number; payload?: TeamStyle }) => (
                  <TeamDot {...props} />
                )}
                onClick={(d) => setSelected(d as unknown as TeamStyle)}
              />
            </ScatterChart>
          </ResponsiveContainer>
          {/* Quadrant labels */}
          <div className="mt-1 grid grid-cols-2 gap-1 text-[10px] text-muted-foreground font-mono">
            <span className="text-right pr-2 border-r border-ink/10">← Handball Chain | Power →</span>
            <span className="pl-2">← Running/Spread | Kick-Mark →</span>
          </div>
        </div>

        {/* Style cards + detail panel */}
        <div className="col-span-12 lg:col-span-5 space-y-3">
          {/* Style legend */}
          <div className="grid grid-cols-2 gap-2">
            {Object.entries(STYLE_COLORS).map(([style, color]) => (
              <div key={style} className="border border-ink/10 rounded p-2 text-xs">
                <div className="flex items-center gap-1.5 mb-0.5">
                  <span className="size-2.5 rounded-full flex-shrink-0" style={{ background: color }} />
                  <span className="font-bold">{style}</span>
                </div>
                <span className="text-muted-foreground leading-tight block">{STYLE_DESCRIPTIONS[style]}</span>
              </div>
            ))}
          </div>

          {/* Selected team detail */}
          {s && (
            <div className="border border-ink/10 rounded p-3 space-y-2">
              <div className="flex items-center gap-2">
                {getLogo(s.team) && <img src={getLogo(s.team)!} alt="" className="size-7" />}
                <div>
                  <p className="font-bold text-sm">{s.team}</p>
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded" style={{ background: STYLE_COLORS[s.style] + "40", color: STYLE_COLORS[s.style] }}>
                    {s.style}
                  </span>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-1.5 text-xs">
                {[
                  ["Contested",  `${(s.contested_ratio * 100).toFixed(1)}%`],
                  ["Kick rate",  `${(s.kick_ratio * 100).toFixed(1)}%`],
                  ["Clearances", `${s.avg_clearances}/g`],
                  ["Tackles",    `${s.avg_tackles}/g`],
                  ["Inside 50s", `${s.avg_inside50}/g`],
                  ["Rebounds",   `${s.avg_rebounds}/g`],
                  ["Goals",      `${s.avg_goals}/g`],
                  ["Clangers",   `${s.avg_clangers}/g`],
                  ["Cont. marks",`${s.avg_cont_marks}/g`],
                ].map(([label, val]) => (
                  <div key={label} className="bg-ink/5 rounded px-2 py-1">
                    <p className="text-muted-foreground text-[9px] uppercase tracking-wider">{label}</p>
                    <p className="font-mono font-bold">{val}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Compact team list */}
          <div className="space-y-0.5 max-h-44 overflow-y-auto">
            {styles.map((t) => (
              <button
                key={t.team}
                onClick={() => setSelected(t)}
                className={`w-full flex items-center gap-2 px-2 py-1 rounded text-xs text-left transition-colors ${s?.team === t.team ? "bg-accent/20" : "hover:bg-ink/5"}`}
              >
                {getLogo(t.team) && <img src={getLogo(t.team)!} alt="" className="size-4" />}
                <span className="flex-1 font-medium">{t.team}</span>
                <span className="size-2 rounded-full" style={{ background: STYLE_COLORS[t.style] }} />
                <span className="text-muted-foreground font-mono">{t.style}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Section 2: Style Matchup Win Rates ───────────────────────────────────────

function StyleMatchupsSection() {
  const { data, isLoading } = useStyleMatchups();
  if (isLoading) return <div className="text-sm text-muted-foreground">Loading matchup data…</div>;
  if (!data) return null;

  return (
    <div className="space-y-4">
      <SectionHeading title="Style vs Style Win Rates" meta="How each style performs against others" />
      <p className="text-sm text-muted-foreground max-w-2xl">
        Win rate of the row style when facing the column style. Red = favourable matchup, blue = unfavourable.
        Based on {Object.values(data.team_styles).length} teams across 2023–2026.
      </p>

      <div className="overflow-x-auto">
        <table className="text-xs border-collapse w-full max-w-2xl">
          <thead>
            <tr>
              <th className="text-left py-2 pr-4 font-mono text-muted-foreground text-[10px] uppercase">vs →</th>
              {data.styles.map((s) => (
                <th key={s} className="py-2 px-3 text-center font-bold whitespace-nowrap">
                  <div className="flex items-center justify-center gap-1">
                    <span className="size-2 rounded-full" style={{ background: STYLE_COLORS[s] }} />
                    <span className="text-[10px]">{s}</span>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.matrix.map((row) => (
              <tr key={row.style} className="border-t border-ink/10">
                <td className="py-2 pr-4 font-bold whitespace-nowrap">
                  <div className="flex items-center gap-1.5">
                    <span className="size-2.5 rounded-full" style={{ background: STYLE_COLORS[row.style] }} />
                    {row.style}
                  </div>
                </td>
                {row.results.map((cell, ci) => {
                  const isDiag = data.styles[ci] === row.style;
                  const wr = cell.win_rate;
                  let cellBg = "bg-transparent";
                  if (!isDiag && wr !== null) {
                    if (wr >= 0.60) cellBg = "bg-red-500/70 text-white";
                    else if (wr >= 0.53) cellBg = "bg-red-300/60";
                    else if (wr <= 0.40) cellBg = "bg-blue-500/70 text-white";
                    else if (wr <= 0.47) cellBg = "bg-blue-300/60";
                  }
                  return (
                    <td key={ci} className={`py-2 px-3 text-center font-mono rounded ${cellBg} ${isDiag ? "opacity-20" : ""}`}>
                      {isDiag ? "—" : wr !== null ? `${(wr * 100).toFixed(0)}%` : "—"}
                      {!isDiag && cell.n > 0 && <div className="text-[9px] opacity-60">n={cell.n}</div>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Style team membership */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4">
        {data.styles.map((style) => (
          <div key={style} className="border border-ink/10 rounded p-2">
            <div className="flex items-center gap-1.5 mb-1.5">
              <span className="size-2.5 rounded-full" style={{ background: STYLE_COLORS[style] }} />
              <span className="text-[10px] font-bold uppercase tracking-wider">{style}</span>
            </div>
            <div className="flex flex-wrap gap-1">
              {(data.style_teams[style] ?? []).map((team) => {
                const logo = getLogo(team);
                return logo
                  ? <img key={team} src={logo} alt={team} className="size-5" title={team} />
                  : <span key={team} className="text-[10px] text-muted-foreground">{team}</span>;
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Section: Role Leaks (per-game classified roles) ──────────────────────────

function RoleLeaksSection() {
  const { data, isLoading } = useRoleLeaks();
  const [highlight, setHighlight] = useState<string | null>(null);

  if (isLoading) return <div className="text-sm text-muted-foreground">Loading role data…</div>;
  if (!data?.available) return null;

  return (
    <div className="space-y-4">
      <SectionHeading title="Role Leak Heatmap" meta="2026 · roles classified per game from box scores" />
      <p className="text-sm text-muted-foreground max-w-2xl">
        Unlike the static positions above, each player-game is classified by where the player{" "}
        <em>actually played that night</em> (a midfielder swung to half-back counts as a Defender
        for that game). <strong className="text-ink">Red = the team leaks more disposals to that
        role than league average</strong>, blue = shuts it down.
      </p>

      <div className="overflow-x-auto">
        <table className="text-xs border-collapse min-w-full">
          <thead>
            <tr>
              <th className="text-left py-2 pr-4 font-mono text-muted-foreground text-[10px] uppercase sticky left-0 bg-paper z-10 min-w-[140px]">Team</th>
              {data.roles.map((role) => (
                <th key={role} className="py-2 px-2 text-center min-w-[90px]">
                  <div className="text-[10px] font-bold">{role}</div>
                  <div className="text-[9px] text-muted-foreground font-normal">
                    lg avg {data.league_avg[role] ?? "—"}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.teams.map((team) => {
              const dim = highlight !== null && highlight !== team.team;
              const logo = getLogo(team.team);
              return (
                <tr
                  key={team.team}
                  onClick={() => setHighlight(highlight === team.team ? null : team.team)}
                  className={`cursor-pointer border-t border-ink/5 transition-opacity ${dim ? "opacity-30" : ""}`}
                >
                  <td className="py-1.5 pr-4 sticky left-0 bg-paper z-10">
                    <span className="flex items-center gap-2 font-bold">
                      {logo && <img src={logo} alt="" className="h-4 w-4" />}
                      {team.team}
                    </span>
                  </td>
                  {data.roles.map((role) => {
                    const r = team.roles.find((x) => x.role === role);
                    if (!r) return <td key={role} className="text-center text-muted-foreground">—</td>;
                    return (
                      <td key={role} className={`py-1.5 px-2 text-center font-mono ${dispColor(r.vs_league)}`}>
                        {r.avg_disposals}
                        <span className="text-[9px] opacity-70"> ({r.vs_league > 0 ? "+" : ""}{r.vs_league})</span>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Biggest leaks + player exploits */}
      <div className="grid gap-6 md:grid-cols-2">
        <div>
          <h4 className="mb-2 font-mono text-[11px] font-bold uppercase text-muted-foreground">
            Biggest role leaks
          </h4>
          <div className="space-y-1">
            {data.notable.filter((n) => n.vs_league > 0).slice(0, 8).map((n, i) => (
              <div key={i} className="flex items-center justify-between border-b border-ink/5 py-1 text-xs">
                <span><span className="font-bold">{n.team}</span> → {n.role}</span>
                <span className="font-mono text-red-600">+{n.vs_league} disp/game</span>
              </div>
            ))}
          </div>
        </div>
        <div>
          <h4 className="mb-2 font-mono text-[11px] font-bold uppercase text-muted-foreground">
            Biggest individual exploits conceded
          </h4>
          <div className="space-y-1">
            {data.exploits.slice(0, 8).map((e, i) => (
              <div key={i} className="flex items-center justify-between border-b border-ink/5 py-1 text-xs">
                <span>
                  <span className="font-bold">{e.player}</span>
                  <span className="text-muted-foreground"> ({e.role}) vs {e.vs_team}</span>
                </span>
                <span className="font-mono">{e.disposals} <span className="text-red-600">(+{e.over} over avg)</span></span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Section 3: Position Concession ───────────────────────────────────────────

function PositionConcessionSection() {
  const { data, isLoading } = usePositionConcession();
  const [view, setView] = useState<"disposals" | "goals">("disposals");
  const [highlight, setHighlight] = useState<string | null>(null);

  if (isLoading) return <div className="text-sm text-muted-foreground">Loading position data…</div>;
  if (!data) return null;
  if (!data.available) {
    return (
      <div className="border border-dashed border-ink/20 rounded p-6 text-center text-sm text-muted-foreground">
        Position data is being scraped. Refresh in a few minutes.
        <p className="text-xs mt-1 opacity-60">{data.reason}</p>
      </div>
    );
  }

  const positions = data.positions ?? POS_ORDER;
  const teams = data.teams ?? [];

  return (
    <div className="space-y-4">
      <SectionHeading title="Position Concession Heatmap" meta="Stats allowed to each position by team" />
      <p className="text-sm text-muted-foreground max-w-2xl">
        How many disposals / goals does each team concede to opponents playing in each position?
        <strong className="text-ink"> Red = more than league average</strong> (exploitable),
        <strong className="text-ink"> blue = fewer</strong> (heavily defended).
        Click a row to highlight that team.
      </p>

      <div className="flex gap-2 text-xs font-mono">
        {(["disposals", "goals"] as const).map((v) => (
          <button
            key={v}
            onClick={() => setView(v)}
            className={`px-3 py-1 rounded border transition-colors ${view === v ? "border-ink bg-ink text-paper" : "border-ink/20 text-muted-foreground hover:border-ink/50"}`}
          >
            {v}
          </button>
        ))}
      </div>

      {/* Heatmap table */}
      <div className="overflow-x-auto">
        <table className="text-xs border-collapse min-w-full">
          <thead>
            <tr>
              <th className="text-left py-2 pr-4 font-mono text-muted-foreground text-[10px] uppercase sticky left-0 bg-paper z-10 min-w-[140px]">Team</th>
              {positions.map((pos) => (
                <th key={pos} className="py-2 px-2 text-center min-w-[90px]">
                  <div className="text-[10px] font-bold">{pos}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {teams.map((team) => {
              const posMap = Object.fromEntries(team.positions.map((p) => [p.position, p]));
              const isHighlighted = highlight === team.team;
              return (
                <tr
                  key={team.team}
                  onClick={() => setHighlight(isHighlighted ? null : team.team)}
                  className={`border-t border-ink/10 cursor-pointer transition-all ${isHighlighted ? "ring-1 ring-inset ring-accent" : "hover:bg-ink/5"}`}
                >
                  <td className="py-1.5 pr-3 sticky left-0 bg-paper z-10">
                    <div className="flex items-center gap-1.5">
                      {getLogo(team.team) && <img src={getLogo(team.team)!} alt="" className="size-4 flex-shrink-0" />}
                      <span className="font-medium whitespace-nowrap">{team.team}</span>
                    </div>
                  </td>
                  {positions.map((pos) => {
                    const row = posMap[pos];
                    if (!row) return <td key={pos} className="py-1.5 px-2 text-center text-muted-foreground">—</td>;
                    const delta = view === "disposals" ? row.disp_vs_avg : row.goal_vs_avg;
                    const val   = view === "disposals" ? row.avg_disposals : row.avg_goals;
                    const colorCls = view === "disposals" ? dispColor(delta) : goalColor(delta);
                    return (
                      <td key={pos} className={`py-1.5 px-2 text-center font-mono rounded ${colorCls}`}>
                        <div>{view === "disposals" ? val.toFixed(1) : val.toFixed(2)}</div>
                        <div className="text-[9px] opacity-70">{delta >= 0 ? "+" : ""}{delta.toFixed(2)}</div>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
          {/* League avg footer */}
          {data.league_avg && (
            <tfoot>
              <tr className="border-t-2 border-ink/20">
                <td className="py-2 pr-3 sticky left-0 bg-paper z-10 font-mono text-[10px] text-muted-foreground uppercase">League avg</td>
                {positions.map((pos) => {
                  const la = data.league_avg!.find((r) => r.position === pos);
                  return (
                    <td key={pos} className="py-2 px-2 text-center font-mono text-muted-foreground">
                      {la ? (view === "disposals" ? la.avg_disposals.toFixed(1) : la.avg_goals.toFixed(2)) : "—"}
                    </td>
                  );
                })}
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      {/* Notable findings */}
      {data.notable && data.notable.length > 0 && (
        <div className="space-y-2 mt-4">
          <h3 className="font-display text-sm font-extrabold uppercase tracking-tighter">Notable Findings</h3>
          <p className="text-xs text-muted-foreground">Biggest deviations from league average — the most exploitable positional matchups.</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {(data.notable as NotableFinding[]).slice(0, 12).map((f, i) => (
              <div
                key={i}
                className={`border border-ink/10 rounded p-2.5 text-xs ${f.disp_vs_avg > 0 ? "border-l-2 border-l-red-500" : "border-l-2 border-l-blue-500"}`}
              >
                <div className="flex items-center gap-1.5 mb-1">
                  {getLogo(f.team) && <img src={getLogo(f.team)!} alt="" className="size-4" />}
                  <span className="font-bold">{f.team}</span>
                  <span className={`ml-auto font-mono font-bold ${f.disp_vs_avg > 0 ? "text-red-500" : "text-blue-500"}`}>
                    {f.disp_vs_avg > 0 ? "+" : ""}{f.disp_vs_avg.toFixed(1)}
                  </span>
                </div>
                <p className="text-muted-foreground leading-tight">
                  {f.direction} disposals to <strong className="text-ink">{f.position}s</strong>
                  {" "}({f.avg_disposals.toFixed(1)} avg vs league avg)
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

function Analysis() {
  const { data: styles, isLoading } = useTeamStyles();

  return (
    <PageShell>
      <div className="space-y-12">
        <div>
          <h1 className="font-display text-4xl font-extrabold uppercase tracking-tighter">
            Tactical Analysis
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Game style profiles, style matchup win rates, and positional concession patterns.
          </p>
        </div>

        {isLoading
          ? <ApiLoading />
          : styles && <TeamStylesSection styles={styles} />
        }

        <StyleMatchupsSection />

        <PositionConcessionSection />

        <RoleLeaksSection />
      </div>
    </PageShell>
  );
}
