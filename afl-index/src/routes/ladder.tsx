import { createFileRoute } from "@tanstack/react-router";
import { PageShell, SectionHeading } from "@/components/page-shell";
import { LadderTable } from "@/components/ladder-table";

export const Route = createFileRoute("/ladder")({
  head: () => ({
    meta: [
      { title: "AFL Ladder · AFL.Index" },
      {
        name: "description",
        content:
          "Full AFL ladder with played, wins, losses, points and percentage for every team.",
      },
      { property: "og:title", content: "AFL Ladder · AFL.Index" },
      {
        property: "og:description",
        content: "Live AFL ladder snapshot for the 2025 season.",
      },
    ],
  }),
  component: LadderPage,
});

function LadderPage() {
  return (
    <PageShell>
      <div className="mx-auto max-w-3xl space-y-6">
        <SectionHeading title="AFL Ladder" meta="After Round 20" />
        <LadderTable />
      </div>
    </PageShell>
  );
}
