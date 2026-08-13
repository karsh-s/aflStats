import { createFileRoute } from "@tanstack/react-router";
import { PageShell, SectionHeading } from "@/components/page-shell";
import { ProjectionsTable } from "@/components/projections-table";
import { PROP_LADDER } from "@/lib/afl-data";

export const Route = createFileRoute("/projections")({
  head: () => ({
    meta: [
      { title: "Player Projections · statsfl" },
      {
        name: "description",
        content:
          "Expected disposals, goals, marks and clearances per AFL player with confidence bands from 4+ to 45+.",
      },
      { property: "og:title", content: "Player Projections · statsfl" },
      {
        property: "og:description",
        content:
          "Expected stats and prop ladders for every AFL player, 4+ disposals through 45+.",
      },
    ],
  }),
  component: ProjectionsPage,
});

function ProjectionsPage() {
  return (
    <PageShell>
      <div className="space-y-8">
        <SectionHeading
          title="Player Projections"
          meta="Bayesian posterior · Last 8 + opponent adj."
        />
        <ProjectionsTable />

        <SectionHeading title="Disposal Prop Ladder" meta="Typical top-6 midfielder" />
        <div className="border border-border bg-card">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-border text-[10px] font-bold uppercase text-muted-foreground">
                <th className="p-3">Line</th>
                <th className="p-3 text-right">Typical Hit %</th>
                <th className="p-3">Distribution</th>
              </tr>
            </thead>
            <tbody className="font-mono text-sm">
              {PROP_LADDER.map((row) => (
                <tr key={row.line} className="border-b border-border last:border-0">
                  <td className="p-3 font-sans font-bold">{row.line}</td>
                  <td className="p-3 text-right text-accent">
                    {row.typical.toFixed(1)}%
                  </td>
                  <td className="p-3">
                    <div className="h-1.5 w-full bg-ink/5">
                      <div
                        className="h-full bg-ink"
                        style={{ width: `${row.typical}%` }}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </PageShell>
  );
}
