import { createFileRoute } from "@tanstack/react-router";
import { PageShell, SectionHeading } from "@/components/page-shell";
import { InsightCard } from "@/components/insight-card";
import { INSIGHTS } from "@/lib/afl-data";
import wetMatrix from "@/assets/wet-weather-matrix.jpg";

export const Route = createFileRoute("/insights")({
  head: () => ({
    meta: [
      { title: "Team Insights · AFL.Index" },
      {
        name: "description",
        content:
          "Play style, stadium form, opponent matchups and weather variance for every AFL team.",
      },
      { property: "og:title", content: "Team Insights · AFL.Index" },
      {
        property: "og:description",
        content:
          "Stadium IQ, weather variance and matchup signals for every AFL side.",
      },
    ],
  }),
  component: InsightsPage,
});

function InsightsPage() {
  return (
    <PageShell>
      <div className="space-y-8">
        <SectionHeading
          title="Team Form Insights"
          meta="Stadium · Opponent · Weather"
        />
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {INSIGHTS.map((i) => (
            <InsightCard key={i.tag} i={i} />
          ))}
        </div>

        <SectionHeading title="Environmental Sensitivity Matrix" meta="2020 – 2024" />
        <div className="border border-border p-4">
          <img
            src={wetMatrix}
            alt="Heat map of AFL team performance variance in wet versus dry weather"
            width={800}
            height={512}
            loading="lazy"
            className="aspect-video w-full object-cover"
          />
          <p className="mt-3 max-w-prose text-pretty text-xs text-muted-foreground">
            Darker clusters indicate teams whose expected score drops more than one
            standard deviation in wet conditions. Sydney, Hawthorn and Brisbane
            historically defend rain best; Adelaide and GWS regress the most.
          </p>
        </div>
      </div>
    </PageShell>
  );
}
