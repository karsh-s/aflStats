import { createFileRoute } from "@tanstack/react-router";
import { useState, useMemo } from "react";
import { PageShell, SectionHeading } from "@/components/page-shell";
import { ApiLoading, ApiOfflineBanner } from "@/components/api-status";
import { useEvents, useGameSGM, useGameTargetMultis } from "@/lib/queries";
import type { APIEvent, APISGMLeg, APITargetMulti } from "@/lib/api";

export const Route = createFileRoute("/multi-builder")({
  head: () => ({
    meta: [
      { title: "SGM Builder · AFL.Index" },
      { name: "description", content: "Build SportsBet same-game multis with calibrated model hit probabilities." },
    ],
  }),
  component: MultiPage,
});

// ── Risk classification ────────────────────────────────────────────────────

type RiskLevel = "low" | "medium" | "high";

function riskLevel(legs: APISGMLeg[]): RiskLevel {
  if (legs.length === 0) return "high";
  const minProb = Math.min(...legs.map((l) => l.prob));
  if (minProb >= 0.68) return "low";
  if (minProb >= 0.52) return "medium";
  return "high";
}

const RISK_META: Record<RiskLevel, { label: string; cls: string; desc: string }> = {
  low:    { label: "LOW RISK",    cls: "bg-green-700 text-white",   desc: "Target ~2.5× · all legs ≥68% model confidence" },
  medium: { label: "MED RISK",   cls: "bg-yellow-600 text-white",  desc: "Target ~5× · legs ≥52% model confidence" },
  high:   { label: "HIGH RISK",  cls: "bg-red-700 text-white",     desc: "Target ~12× · best available legs at any confidence" },
};

// ── Auto multi algorithm ───────────────────────────────────────────────────

function buildMulti(
  legs: APISGMLeg[],
  target: number,
  maxLegs = 8,
  minOddsFloor?: number,
): { legs: APISGMLeg[]; combinedOdds: number; jointProb: number } | null {
  const minOdds = minOddsFloor ?? Math.max(1.05, Math.pow(target, 1 / maxLegs));

  // Deduplicate: one best (highest-prob) leg per player within the odds floor.
  const playerBest = new Map<string, APISGMLeg>();
  for (const leg of legs) {
    if (leg.odds < minOdds) continue;
    const prev = playerBest.get(leg.player);
    if (!prev || leg.prob > prev.prob) {
      playerBest.set(leg.player, leg);
    }
  }

  const pool = [...playerBest.values()].sort((a, b) => b.prob - a.prob);
  if (pool.length < 2) return null;

  const picked: APISGMLeg[] = [];
  let combinedOdds = 1;

  for (const leg of pool) {
    if (picked.length >= maxLegs) break;
    const newOdds = combinedOdds * leg.odds;
    const maxOdds = combinedOdds >= target * 0.6 ? target * 1.7 : target * 1.4;
    if (newOdds > maxOdds) continue;
    picked.push(leg);
    combinedOdds = newOdds;
    if (combinedOdds >= target) break;
  }

  if (picked.length < 2) return null;
  const jointProb = picked.reduce((acc, l) => acc * l.prob, 1);
  return { legs: picked, combinedOdds, jointProb };
}

// ── Multi card ─────────────────────────────────────────────────────────────

function MultiCard({ target, result }: { target: number; result: APITargetMulti["result"] }) {
  if (!result) {
    return (
      <div className="border border-border p-4 text-xs text-muted-foreground">
        ~{target}× — not enough legs available to reach this target.
      </div>
    );
  }

  const risk = riskLevel(result.legs);
  const rm = RISK_META[risk];
  const allSameStat = new Set(result.legs.map((l) => l.stat)).size === 1;

  return (
    <div className="border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border bg-ink/5 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="font-display font-extrabold uppercase tracking-tighter">
            ~{target}× · {result.legs.length} legs
          </span>
          <span className={`px-1.5 py-0.5 font-mono text-[9px] font-bold ${rm.cls}`}>
            {rm.label}
          </span>
        </div>
        <div className="flex gap-4 font-mono text-xs">
          <span>
            <span className="text-muted-foreground">Odds </span>
            <span className="font-bold">{result.combined_odds.toFixed(2)}×</span>
          </span>
          <span>
            <span className="text-muted-foreground">Hit P </span>
            <span className="font-bold text-accent">
              {(result.joint_prob * 100).toFixed(1)}%
            </span>
          </span>
          <span>
            <span className="text-muted-foreground">Edge </span>
            <span className={`font-bold ${result.edge >= 0 ? "text-green-600" : "text-red-600"}`}>
              {result.edge >= 0 ? "+" : ""}{(result.edge * 100).toFixed(1)}%
            </span>
          </span>
        </div>
      </div>
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-border text-[10px] font-bold uppercase text-muted-foreground">
            <th className="p-3">Player</th>
            <th className="p-3">Leg</th>
            <th className="p-3 text-right">SB Odds</th>
            <th className="p-3 text-right">Model P</th>
          </tr>
        </thead>
        <tbody className="font-mono text-xs">
          {result.legs.map((l, i) => (
            <tr key={i} className="border-b border-border last:border-0 hover:bg-accent/5">
              <td className="p-3 font-sans font-bold">{l.player}</td>
              <td className="p-3 capitalize text-muted-foreground">
                {l.stat === "team"
                  ? <span className="font-bold text-ink">match winner</span>
                  : <>{l.stat} <span className="font-bold text-ink">{l.milestone}</span></>}
              </td>
              <td className="p-3 text-right font-bold">{l.odds.toFixed(2)}</td>
              <td className="p-3 text-right text-accent">{(l.prob * 100).toFixed(0)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
      {result.reasons?.length > 0 && (
        <div className="border-t border-dashed border-border px-4 py-2.5">
          <div className="mb-1 font-mono text-[9px] font-bold uppercase tracking-widest text-muted-foreground">
            Why these legs
          </div>
          <ul className="space-y-1">
            {result.reasons.map((r, i) => (
              <li key={i} className="text-[11px] leading-snug text-ink/80">
                <span className="mr-1.5 text-accent">▸</span>{r}
              </li>
            ))}
          </ul>
        </div>
      )}
      {allSameStat && (
        <div className="border-t border-dashed border-border px-4 py-2 text-[10px] text-muted-foreground">
          All legs are {result.legs[0].stat} — correlated. Actual hit-rate will be lower than the
          independent estimate.
        </div>
      )}
    </div>
  );
}

// ── Risk multi cards (Low/Med/High sections) ───────────────────────────────

// Build a multi from legs that meet a minimum prob + odds floor, targeting a given combined odds.
function buildByRisk(
  legs: APISGMLeg[],
  minProb: number,
  targetOdds: number,
  minOdds: number,
  maxLegs = 8,
) {
  const filtered = legs.filter((l) => l.prob >= minProb);
  return buildMulti(filtered, targetOdds, maxLegs, minOdds);
}

function RiskMultiCard({
  risk,
  result,
}: {
  risk: RiskLevel;
  result: { legs: APISGMLeg[]; combinedOdds: number; jointProb: number } | null;
}) {
  const rm = RISK_META[risk];

  if (!result) {
    return (
      <div className="border border-border p-4 text-xs text-muted-foreground">
        {rm.label} — not enough legs at this confidence level.
      </div>
    );
  }

  const allSameStat = new Set(result.legs.map((l) => l.stat)).size === 1;

  return (
    <div className="border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border bg-ink/5 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className={`px-2 py-0.5 font-mono text-[9px] font-bold ${rm.cls}`}>
            {rm.label}
          </span>
          <span className="font-display font-extrabold uppercase tracking-tighter">
            {result.legs.length} legs
          </span>
        </div>
        <div className="flex gap-4 font-mono text-xs">
          <span>
            <span className="text-muted-foreground">Combined </span>
            <span className="font-bold">{result.combinedOdds.toFixed(2)}×</span>
          </span>
          <span>
            <span className="text-muted-foreground">Hit P </span>
            <span className="font-bold text-accent">
              {(result.jointProb * 100).toFixed(1)}%
            </span>
          </span>
        </div>
      </div>
      <table className="w-full text-left">
        <thead>
          <tr className="border-b border-border text-[10px] font-bold uppercase text-muted-foreground">
            <th className="p-3">Player</th>
            <th className="p-3">Leg</th>
            <th className="p-3 text-right">SB Odds</th>
            <th className="p-3 text-right">Model P</th>
          </tr>
        </thead>
        <tbody className="font-mono text-xs">
          {result.legs.map((l, i) => (
            <tr key={i} className="border-b border-border last:border-0 hover:bg-accent/5">
              <td className="p-3 font-sans font-bold">{l.player}</td>
              <td className="p-3 capitalize text-muted-foreground">
                {l.stat === "team"
                  ? <span className="font-bold text-ink">match winner</span>
                  : <>{l.stat} <span className="font-bold text-ink">{l.milestone}</span></>}
              </td>
              <td className="p-3 text-right font-bold">{l.odds.toFixed(2)}</td>
              <td className="p-3 text-right text-accent">{(l.prob * 100).toFixed(0)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
      {allSameStat && (
        <div className="border-t border-dashed border-border px-4 py-2 text-[10px] text-muted-foreground">
          All legs are {result.legs[0].stat} — correlated stat, real hit-rate will be lower.
        </div>
      )}
      <div className="border-t border-dashed border-border px-4 py-2 text-[10px] text-muted-foreground">
        {rm.desc}
      </div>
    </div>
  );
}

// ── Manual builder ─────────────────────────────────────────────────────────

function ManualBuilder({ legs }: { legs: APISGMLeg[] }) {
  const [selected, setSelected] = useState<string[]>([]);
  const pool = useMemo(() => {
    const seen = new Set<string>();
    return legs.filter((l) => {
      const key = `${l.player}|${l.stat}|${l.milestone}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }, [legs]);

  const chosenLegs = pool.filter((l) =>
    selected.includes(`${l.player}|${l.stat}|${l.milestone}`),
  );
  const combinedOdds = chosenLegs.reduce((acc, l) => acc * l.odds, 1);
  const jointProb = chosenLegs.reduce((acc, l) => acc * l.prob, 1);
  const hasSamePlayer = chosenLegs.some(
    (l) => chosenLegs.filter((m) => m.player_scraped === l.player_scraped).length > 1,
  );
  const risk = riskLevel(chosenLegs);
  const rm = chosenLegs.length >= 2 ? RISK_META[risk] : null;

  function toggle(key: string) {
    setSelected((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    );
  }

  return (
    <div className="space-y-4">
      {chosenLegs.length >= 2 && (
        <div className="border border-border bg-card">
          <div className="flex items-center justify-between border-b border-border bg-ink/5 px-4 py-2">
            <div className="flex items-center gap-2">
              <span className="font-mono text-[11px] font-bold uppercase">
                Your multi · {chosenLegs.length} legs
              </span>
              {rm && (
                <span className={`px-1.5 py-0.5 font-mono text-[9px] font-bold ${rm.cls}`}>
                  {rm.label}
                </span>
              )}
            </div>
            <div className="flex gap-4 font-mono text-xs">
              <span>
                <span className="text-muted-foreground">Odds </span>
                <span className="font-bold">{combinedOdds.toFixed(2)}×</span>
              </span>
              <span>
                <span className="text-muted-foreground">Hit P </span>
                <span className={`font-bold ${jointProb >= 0.5 ? "text-accent" : ""}`}>
                  {(jointProb * 100).toFixed(1)}%
                </span>
              </span>
            </div>
          </div>
          {hasSamePlayer && (
            <div className="border-b border-border px-4 py-2 text-[10px] text-accent">
              ⚠ Same player selected twice — SportsBet typically blocks correlated same-player legs.
            </div>
          )}
          <table className="w-full text-left">
            <tbody className="font-mono text-xs">
              {chosenLegs.map((l) => {
                const key = `${l.player}|${l.stat}|${l.milestone}`;
                return (
                  <tr key={key} className="border-b border-border last:border-0">
                    <td className="p-3 font-sans font-bold">{l.player}</td>
                    <td className="p-3 capitalize text-muted-foreground">
                      {l.stat} <span className="font-bold text-ink">{l.milestone}</span>
                    </td>
                    <td className="p-3 text-right font-bold">{l.odds.toFixed(2)}</td>
                    <td className="p-3 text-right text-accent">{(l.prob * 100).toFixed(0)}%</td>
                    <td className="p-3 text-right">
                      <button
                        onClick={() => toggle(key)}
                        className="font-mono text-[10px] text-muted-foreground hover:text-accent"
                      >
                        ✕
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="border border-border bg-card">
        <div className="border-b border-border bg-ink/5 px-4 py-2">
          <span className="font-mono text-[11px] font-bold uppercase">All available legs</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-border text-[10px] font-bold uppercase text-muted-foreground">
                <th className="p-3" />
                <th className="p-3">Player</th>
                <th className="p-3">Stat · Line</th>
                <th className="p-3 text-right">Odds</th>
                <th className="p-3 text-right">Model P</th>
              </tr>
            </thead>
            <tbody className="font-mono text-xs">
              {pool.map((l) => {
                const key = `${l.player}|${l.stat}|${l.milestone}`;
                const picked = selected.includes(key);
                return (
                  <tr
                    key={key}
                    onClick={() => toggle(key)}
                    className={`cursor-pointer border-b border-border last:border-0 transition-colors ${picked ? "bg-accent/10 hover:bg-accent/15" : "hover:bg-ink/5"}`}
                  >
                    <td className="p-3">
                      <span
                        className={`inline-block size-4 border font-bold text-center font-mono text-[10px] leading-4 ${picked ? "border-ink bg-ink text-paper" : "border-border"}`}
                      >
                        {picked ? "✓" : ""}
                      </span>
                    </td>
                    <td className="p-3 font-sans font-bold">{l.player}</td>
                    <td className="p-3 capitalize text-muted-foreground">
                      {l.stat} <span className="font-bold text-ink">{l.milestone}</span>
                    </td>
                    <td className="p-3 text-right font-bold">{l.odds.toFixed(2)}</td>
                    <td className="p-3 text-right text-accent">{(l.prob * 100).toFixed(0)}%</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────


function MultiPage() {
  const { data: events, isLoading: evLoading, isError: evError } = useEvents();
  const [selectedGame, setSelectedGame] = useState<string>("");
  const [mode, setMode] = useState<"risk" | "target" | "manual">("risk");

  const eventId = selectedGame || (events?.[0]?.id ?? null);
  const [safeMode, setSafeMode] = useState(false);
  const { data: legs, isLoading: legsLoading } = useGameSGM(eventId);
  // Post-mortem R18: legs under 70% model probability hit far below their
  // claimed rate — 0.70 is now the default floor; the toggle goes to 0.80.
  const { data: targetMultis, isLoading: multisLoading } = useGameTargetMultis(
    eventId, safeMode ? 0.8 : 0.7,
  );

  // Each tier targets a different odds range and probability floor.
  // minOdds floor prevents the algorithm from stacking 1.03 certainties that add nothing.
  const lowResult  = useMemo(() => legs ? buildByRisk(legs, 0.65, 2.5,  1.15, 5)  : null, [legs]);
  const medResult  = useMemo(() => legs ? buildByRisk(legs, 0.50, 5.0,  1.25, 7)  : null, [legs]);
  const highResult = useMemo(() => legs ? buildByRisk(legs, 0.30, 12.0, 1.50, 10) : null, [legs]);

  return (
    <PageShell>
      <div className="space-y-6">
        {evError && !evLoading && <ApiOfflineBanner />}

        <SectionHeading title="Same Game Multi Creator" meta="SportsBet SGM · Calibrated model" />

        {/* Game selector */}
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-mono text-[11px] font-bold uppercase text-muted-foreground">
            Game:
          </span>
          {evLoading && <ApiLoading label="Loading games…" />}
          {events?.map((ev: APIEvent) => (
            <button
              key={ev.id}
              onClick={() => setSelectedGame(ev.id)}
              className={`border px-3 py-1.5 font-mono text-[11px] font-bold uppercase transition-colors ${
                eventId === ev.id
                  ? "border-ink bg-ink text-paper"
                  : "border-border text-muted-foreground hover:border-ink hover:text-ink"
              }`}
            >
              {ev.home} v {ev.away}
            </button>
          ))}
        </div>

        {/* Mode tabs */}
        <div className="flex gap-0 border-b border-border">
          {(["risk", "target", "manual"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`border-b-2 px-6 py-2.5 text-[11px] font-bold uppercase tracking-widest transition-colors ${
                mode === m
                  ? "-mb-px border-ink text-ink"
                  : "border-transparent text-muted-foreground hover:text-ink"
              }`}
            >
              {m === "risk" ? "⚡ By risk level" : m === "target" ? "🎯 By target odds" : "🛠 Build your own"}
            </button>
          ))}
        </div>

        {legsLoading && <ApiLoading label="Pricing milestone legs…" />}

        {/* By risk level */}
        {legs && legs.length > 0 && mode === "risk" && (
          <div className="space-y-4">
            <p className="text-xs text-muted-foreground max-w-prose">
              Three multis built from the highest-probability legs available, grouped by risk.
              Low risk uses only legs where the model is highly confident (≥68%). Medium includes
              slight favourites (≥52%). High includes any available leg.
            </p>
            <RiskMultiCard risk="low" result={lowResult} />
            <RiskMultiCard risk="medium" result={medResult} />
            <RiskMultiCard risk="high" result={highResult} />
          </div>
        )}

        {/* By target odds */}
        {mode === "target" && (
          <div className="space-y-4">
            <button
              onClick={() => setSafeMode(!safeMode)}
              className={`border px-3 py-1.5 font-mono text-[11px] font-bold uppercase transition-colors ${
                safeMode
                  ? "border-ink bg-ink text-paper"
                  : "border-border text-muted-foreground hover:border-ink hover:text-ink"
              }`}
            >
              {safeMode ? "✓ " : ""}Ultra-safe (every leg ≥80%)
            </button>
            {multisLoading && <ApiLoading label="Optimising safest multis…" />}
            {targetMultis?.map((tm) => (
              <MultiCard key={tm.target} target={tm.target} result={tm.result} />
            ))}
          </div>
        )}

        {/* Manual builder */}
        {legs && legs.length > 0 && mode === "manual" && (
          <div>
            <p className="text-xs text-muted-foreground mb-4">
              Click any row to add/remove a leg. Combined odds and hit probability update live.
            </p>
            <ManualBuilder legs={legs} />
          </div>
        )}

        {legs?.length === 0 && !legsLoading && (
          <div className="border border-border p-6 text-center text-sm text-muted-foreground">
            No SportsBet player markets available for this game yet.
          </div>
        )}

        <p className="text-[10px] text-muted-foreground max-w-prose">
          Combined odds = product of legs. SportsBet's actual SGM price includes correlation
          adjustments and is usually shorter. Goal and disposal legs are sourced from the Odds API
          — marks are model-only (no Odds API market available). Gamble responsibly — 18+.
        </p>
      </div>
    </PageShell>
  );
}
