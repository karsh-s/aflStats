import { useMemo } from "react";
import { useLadder, usePlayerStats } from "@/lib/queries";
import { TEAM_NAMES, type TeamCode } from "@/lib/afl-data";

type Item = { tag: string; text: string };

/**
 * Scrolling footer built from live season data (ladder + player stats).
 * Deliberately carries no model/projection content — results and raw stats
 * only, so it never implies a betting opinion.
 */
function buildItems(
  ladder: { pos: number; team: string; wins: number; losses: number; played: number; pct: number; points: number }[] | undefined,
  players: Record<string, string | number>[] | undefined,
): Item[] {
  const items: Item[] = [];
  const name = (code: string) => TEAM_NAMES[code as TeamCode] ?? code;

  if (ladder?.length) {
    const top = ladder[0];
    items.push({
      tag: "LADDER",
      text: `${name(top.team)} lead on ${top.points} pts — ${top.wins}-${top.losses} from ${top.played}`,
    });
    const bestPct = [...ladder].sort((a, b) => b.pct - a.pct)[0];
    if (bestPct) {
      items.push({
        tag: "FORM",
        text: `${name(bestPct.team)} best percentage at ${bestPct.pct.toFixed(1)}%`,
      });
    }
    const eighth = ladder[7];
    const ninth = ladder[8];
    if (eighth && ninth) {
      items.push({
        tag: "EIGHT",
        text: `${name(eighth.team)} hold 8th on ${eighth.points} pts from ${name(ninth.team)}`,
      });
    }
  }

  if (players?.length) {
    const byNum = (p: Record<string, string | number>, k: string) => Number(p[k] ?? 0);
    // Leaders should not be decided by someone with two games played.
    players = players.filter((p) => byNum(p, "gm") >= 5);
    const topDisp = [...players].sort((a, b) => byNum(b, "diAvg") - byNum(a, "diAvg"))[0];
    if (topDisp) {
      items.push({
        tag: "DISPOSALS",
        text: `${topDisp.player} (${topDisp.team}) averaging ${byNum(topDisp, "diAvg").toFixed(1)} from ${byNum(topDisp, "gm")} games`,
      });
    }
    const topGoals = [...players].sort((a, b) => byNum(b, "gl") - byNum(a, "gl"))[0];
    if (topGoals) {
      items.push({
        tag: "GOALS",
        text: `${topGoals.player} (${topGoals.team}) leads with ${byNum(topGoals, "gl")} goals`,
      });
    }
    const topTackles = [...players].sort((a, b) => byNum(b, "tkAvg") - byNum(a, "tkAvg"))[0];
    if (topTackles) {
      items.push({
        tag: "TACKLES",
        text: `${topTackles.player} (${topTackles.team}) averaging ${byNum(topTackles, "tkAvg").toFixed(1)} tackles`,
      });
    }
  }

  return items;
}

export function TickerFooter() {
  const { data: ladder } = useLadder();
  // min_games=1 is the only variant the static export snapshots, so reuse it
  // (and share the stats page's cache) rather than requesting a 404.
  const { data: players } = usePlayerStats(1);

  const items = useMemo(() => {
    const built = buildItems(ladder, players as Record<string, string | number>[] | undefined);
    // Duplicate so the marquee loops seamlessly.
    return built.length ? [...built, ...built] : [];
  }, [ladder, players]);

  if (!items.length) return null;

  return (
    <footer className="fixed bottom-0 z-40 flex h-8 w-full items-center overflow-hidden bg-ink text-paper">
      <div className="animate-ticker flex shrink-0 items-center gap-10 whitespace-nowrap px-4">
        {items.map((it, i) => (
          <div key={i} className="flex items-center gap-2 font-mono text-[10px]">
            <span className="uppercase text-paper/40">{it.tag}</span>
            <span className="font-bold">{it.text}</span>
          </div>
        ))}
      </div>
    </footer>
  );
}
