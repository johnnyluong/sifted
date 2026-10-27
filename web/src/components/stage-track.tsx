import type { JSX } from "react";
import { type Item, STAGES, type Stage } from "@/api";
import { STAGE_LABELS } from "@/lib/vocabulary";

export type StepState = "done" | "active" | "queued" | "waiting" | "failed" | "todo";

type Staged = Pick<Item, "stage" | "status" | "in_motion">;

export function stageSteps(item: Staged): { stage: Stage; state: StepState }[] {
  const index = item.stage === null ? STAGES.length : STAGES.indexOf(item.stage);
  return STAGES.map((stage, i) => ({
    stage,
    state: i < index ? "done" : i > index ? "todo" : current(item),
  }));
}

function current(item: Staged): StepState {
  switch (item.status) {
    case "fetching":
    case "processing":
      return "active";
    case "failed":
      return "failed";
    case "queued":
      return item.in_motion ? "queued" : "waiting";
    default:
      return "done";
  }
}

export function StageTrack({ item }: { item: Item }): JSX.Element {
  const steps = stageSteps(item);
  return (
    <div className="stage-track" role="img" aria-label={trackLabel(steps)}>
      {steps.map((step, i) => (
        <span key={step.stage} className="contents">
          {i > 0 && <span className="stage-link" data-done={steps[i - 1]?.state === "done"} />}
          <span className="stage-dot" data-state={step.state} />
        </span>
      ))}
    </div>
  );
}

function trackLabel(steps: { stage: Stage; state: StepState }[]): string {
  const done = steps.filter((s) => s.state === "done").length;
  return `${done} of ${steps.length} stages done`;
}

export function StageAxis(): JSX.Element {
  return (
    <div aria-hidden className="stage-track mb-2 justify-between font-mono text-[10.5px] text-silt leading-[14px]">
      {STAGES.map((stage) => (
        <span key={stage} className="flex w-0 justify-center whitespace-nowrap">
          {STAGE_LABELS[stage]}
        </span>
      ))}
    </div>
  );
}
