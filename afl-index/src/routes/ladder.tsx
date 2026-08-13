import { createFileRoute } from "@tanstack/react-router";
import { PageShell, SectionHeading } from "@/components/page-shell";
import { LadderTable } from "@/components/ladder-table";
import { useLadder } from "@/lib/queries";

export const Route = createFileRoute("/ladder")({
  head: () => ({
    meta: [
      { title: "AFL Ladder · statsfl" },
      {
        name: "description",
        content:
          "Full AFL ladder with played, wins, losses, points and percentage for every team.",
      },
      { property: "og:title", content: "AFL Ladder · statsfl" },
      {
        property: "og:description",
        content: "Live AFL ladder, updated automatically as results land.",
      },
    ],
  }),
  component: LadderPage,
});

function LadderPage() {
  const { data: ladder } = useLadder();
  const played = ladder?.length ? Math.max(...ladder.map((r) => r.played)) : null;
  const ladderMeta = played ? `After Round ${played}` : "Live";
  return (
    <PageShell>
      <div className="mx-auto max-w-3xl space-y-6">
        <SectionHeading title="AFL Ladder" meta={ladderMeta} />
        <LadderTable />
      </div>
    </PageShell>
  );
}
