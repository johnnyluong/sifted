import { createRoute } from "@tanstack/react-router";
import type { JSX } from "react";
import { Page, PageHeader, PageSection } from "@/components/page";
import type { StepState } from "@/components/stage-track";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Tag } from "@/components/ui/tag";
import {
  type Progress,
  ROADMAP_SET_ASIDE,
  ROADMAP_STAGES,
  ROADMAP_TAGS,
  ROADMAP_UPDATED,
  type RoadmapEntry,
  type RoadmapStage,
} from "@/lib/roadmap";
import { cn } from "@/lib/utils";
import { rootRoute } from "./root";

export const roadmapRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/roadmap",
  component: RoadmapPage,
});

const DOT: Record<Progress, StepState> = { built: "done", next: "queued", later: "waiting" };

function RoadmapPage(): JSX.Element {
  const today = ROADMAP_STAGES.findIndex((s) => s.progress !== "built");
  return (
    <Page>
      <PageHeader
        title="Roadmap"
        subtitle="A saved post should never go to the void. This is what Sift builds next, in order."
      />
      <p className="mb-8 font-mono text-micro text-silt">Updated {ROADMAP_UPDATED}</p>
      <ol>
        {ROADMAP_STAGES.map((stage, i) => (
          <Stage key={stage.title} stage={stage} today={i === today} last={i === ROADMAP_STAGES.length - 1} />
        ))}
      </ol>
      <PageSection title="What the tags mean">
        <dl className="surface surface-pad grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-3 gap-y-2.5">
          {Object.values(ROADMAP_TAGS).map((tag) => (
            <div key={tag.label} className="contents">
              <dt>
                <Tag>{tag.label}</Tag>
              </dt>
              <dd className="text-ink-soft">{tag.meaning}</dd>
            </div>
          ))}
        </dl>
      </PageSection>
      <PageSection title="Looked at and set aside">
        <p className="surface surface-pad text-ink-soft">{ROADMAP_SET_ASIDE}</p>
      </PageSection>
    </Page>
  );
}

function Stage({ stage, today, last }: { stage: RoadmapStage; today: boolean; last: boolean }): JSX.Element {
  const built = stage.progress === "built";
  return (
    <li>
      {today && (
        <div className="mb-8 flex items-center gap-2.5">
          <span className="font-mono text-brass text-micro">Today</span>
          <span className="h-px flex-1 bg-brass" />
        </div>
      )}
      <div className={cn("relative grid grid-cols-[7px_minmax(0,1fr)] gap-x-4", !last && "pb-10")}>
        {!last && (
          <span
            aria-hidden
            className={cn("absolute top-3 bottom-0 left-[3px] w-px", built ? "bg-graphite" : "bg-mesh")}
          />
        )}
        <span className="stage-dot relative mt-[3.5px]" data-state={DOT[stage.progress]} />
        <div className="min-w-0">
          <Eyebrow as="p" className={cn(today && "text-graphite")}>
            {stage.when}
          </Eyebrow>
          <h2 className="mt-1 font-display font-[620] text-[19px] leading-6 tracking-[-0.01em]">{stage.title}</h2>
          <p className="mt-1 max-w-[68ch] text-silt">{stage.intro}</p>
          <ul className="mt-3.5 surface divide-y divide-mesh">
            {stage.entries.map((entry) => (
              <Entry key={entry.title} entry={entry} />
            ))}
          </ul>
        </div>
      </div>
    </li>
  );
}

function Entry({ entry }: { entry: RoadmapEntry }): JSX.Element {
  return (
    <li className="flex items-start justify-between gap-4 px-4 py-3.5 max-[700px]:flex-col max-[700px]:gap-2">
      <div className="min-w-0">
        <p className="font-semibold">{entry.title}</p>
        <p className="mt-0.5 text-ink-soft">{entry.body}</p>
      </div>
      <div className="flex shrink-0 flex-wrap gap-1 pt-0.5">
        {entry.yours && <Tag className="border-brass/40 bg-brass-wash text-brass">Your idea</Tag>}
        {entry.tags.map((tag) => (
          <Tag key={tag}>{ROADMAP_TAGS[tag].label}</Tag>
        ))}
      </div>
    </li>
  );
}
