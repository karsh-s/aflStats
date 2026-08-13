import { Link } from "@tanstack/react-router";
import { useCurrentRound } from "@/lib/queries";

const NAV = [
  { to: "/", label: "Live Terminal" },
  { to: "/multi-builder", label: "Multi-Builder" },
  { to: "/ladder", label: "Ladder" },
  { to: "/stats", label: "Stats" },
  { to: "/premiership-window", label: "Premiership Window" },
  { to: "/analysis", label: "Analysis" },
] as const;

export function SiteHeader() {
  // Round label follows the fixture data instead of being hardcoded.
  const { data: cr } = useCurrentRound();
  const roundLabel = cr?.round ? `Round ${cr.round}` : "Live";
  return (
    <nav className="sticky top-0 z-50 border-b border-ink/10 bg-paper/90 backdrop-blur-md">
      <div className="mx-auto flex h-12 max-w-[1440px] items-center justify-between px-4">
        <div className="flex items-center gap-8">
          <Link
            to="/"
            className="font-display text-xl font-extrabold uppercase tracking-tighter text-ink"
          >
            statsfl
          </Link>
          <div className="hidden gap-4 text-[11px] font-bold uppercase tracking-widest md:flex">
            {NAV.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                className="text-muted-foreground transition-colors hover:text-ink"
                activeProps={{ className: "text-ink" }}
                activeOptions={{ exact: item.to === "/" }}
              >
                {item.label}
              </Link>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="size-2 animate-pulse rounded-full bg-accent" />
          <span className="font-mono text-[10px] font-medium uppercase">
            {roundLabel} · Live Model
          </span>
        </div>
      </div>
    </nav>
  );
}
