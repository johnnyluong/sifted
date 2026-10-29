import { useSuspenseQuery } from "@tanstack/react-query";
import { createRoute, Link } from "@tanstack/react-router";
import { FileArchive } from "lucide-react";
import { type DragEvent, type JSX, useEffect, useId, useState } from "react";
import { toast } from "sonner";
import {
  api,
  type Estimate,
  type Import,
  type ImportAction,
  useImportAction,
  useImportEstimate,
  useStatus,
  useUploadImport,
} from "@/api";
import { Page, PageHeader } from "@/components/page";
import { Button } from "@/components/ui/button";
import { FieldError } from "@/components/ui/field";
import { formatDay, formatMoment } from "@/lib/format";
import { formatCountdown, formatDuration, formatGap, formatPerPost, formatUsd, progress } from "@/lib/imports";
import { cn } from "@/lib/utils";
import { HOLDS, IMPORT_ACTIONS, IMPORT_PHASES, PAUSE_REASONS } from "@/lib/vocabulary";
import { rootRoute } from "./root";

export const importRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/import",
  loader: ({ context }) => context.queryClient.ensureQueryData(api.imports),
  component: ImportPage,
});

function ImportPage(): JSX.Element {
  const { data: imports } = useSuspenseQuery(api.imports);
  return (
    <Page>
      <PageHeader title="Import saved posts" subtitle="Bring in what you saved on Instagram before Sift existed." />
      <ExportSteps open={imports.length === 0} />
      <ExportDrop />
      <div className="mt-6 flex flex-col gap-4">
        {imports.map((view) => (
          <ImportCard key={view.id} view={view} />
        ))}
      </div>
    </Page>
  );
}

const STEPS = [
  "In Instagram, open Accounts Center > Your information and permissions > Download your information.",
  "Choose Some of your information and tick Saved. Format JSON, date range All time. Media quality does not matter.",
  "Meta emails a zip, usually within a few hours. Drop it below.",
];

export function ExportSteps({ open }: { open: boolean }): JSX.Element {
  return (
    <details open={open} className="group surface surface-pad mb-4">
      <summary className="-my-3 cursor-pointer list-none py-3 font-semibold marker:hidden">
        Get the file from Meta
        <span className="ml-2 font-normal text-caption text-silt group-open:hidden">Show the three steps</span>
      </summary>
      <ol className="mt-3 flex flex-col gap-2">
        {STEPS.map((step, i) => (
          <li key={step} className="grid grid-cols-[20px_minmax(0,1fr)] gap-2 text-ink-soft">
            <span className="font-mono text-silt">{i + 1}</span>
            <span>{step}</span>
          </li>
        ))}
      </ol>
    </details>
  );
}

export function ExportDrop(): JSX.Element {
  const upload = useUploadImport();
  const [over, setOver] = useState(false);
  const inputId = useId();
  const send = (file: File | undefined) => {
    if (!file) return;
    upload.mutate(file, { onSuccess: (view) => toast(`Read ${view.filename}`) });
  };
  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setOver(false);
    send(event.dataTransfer.files[0]);
  };
  return (
    <div>
      <label
        htmlFor={inputId}
        onDragOver={(event) => {
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
        className={cn(
          "flex cursor-pointer flex-col items-center gap-1.5 rounded-lg border border-mesh border-dashed px-6 py-9 text-center transition-colors hover:bg-pan-hover",
          over && "border-graphite bg-pan-hover",
          upload.isPending && "pointer-events-none opacity-60",
        )}
      >
        <FileArchive aria-hidden className="size-5 text-silt" strokeWidth={1.6} />
        <span className="font-semibold">
          {upload.isPending ? (
            "Reading the export..."
          ) : (
            <>
              <span className="max-[700px]:hidden">Drop the export here, or choose the zip</span>
              <span className="hidden max-[700px]:inline">Choose the export zip</span>
            </>
          )}
        </span>
        <span className="max-w-[52ch] text-caption text-silt">
          Sift opens only the files for saved posts, and deletes the zip once it has read them. Nothing is sent to
          Instagram until you start.
        </span>
        <input
          id={inputId}
          type="file"
          accept=".zip,application/zip"
          className="sr-only"
          disabled={upload.isPending}
          onChange={(event) => {
            send(event.target.files?.[0]);
            event.target.value = "";
          }}
        />
      </label>
      {upload.error && <FieldError className="px-1 pt-2">{upload.error.message}</FieldError>}
    </div>
  );
}

function ImportCard({ view }: { view: Import }): JSX.Element {
  switch (view.phase) {
    case "preview":
      return <ImportManifest view={view} />;
    case "running":
    case "paused":
      return <ImportProgress view={view} />;
    case "finished":
    case "cancelled":
      return <ImportSummary view={view} />;
  }
}

function CardHeader({ view, tone }: { view: Import; tone?: "alarm" }): JSX.Element {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <span className="truncate font-mono text-caption text-silt">{view.filename}</span>
      <span className={cn("shrink-0 font-[560] text-[13px]", tone === "alarm" ? "text-alarm" : "text-graphite")}>
        {IMPORT_PHASES[view.phase]}
      </span>
    </div>
  );
}

function useImportActionRunner(view: Import): {
  run: (action: ImportAction, limit?: number | null) => void;
  pending: boolean;
} {
  const act = useImportAction();
  return {
    pending: act.isPending,
    run: (action, limit) =>
      act.mutate({ id: view.id, action, limit }, { onSuccess: () => toast(IMPORT_ACTIONS[action].done) }),
  };
}

type Choice = { kind: "option"; limit: number | null } | { kind: "custom" };

export function ImportManifest({ view }: { view: Import }): JSX.Element {
  const { counts } = view;
  const preferred = view.options.find((o) => o.limit === 100) ?? view.options.at(-1);
  const [choice, setChoice] = useState<Choice>({ kind: "option", limit: preferred?.limit ?? null });
  const [custom, setCustom] = useState(Math.min(counts.found, 25));
  const { run, pending } = useImportActionRunner(view);
  const group = useId();
  const customLimit = Math.min(custom, counts.found);
  const posts =
    choice.kind === "custom"
      ? customLimit
      : (view.options.find((o) => o.limit === choice.limit)?.estimate.posts ?? counts.found);
  const limit = choice.kind === "custom" ? customLimit : choice.limit;

  return (
    <section aria-label={`Import ${view.filename}`} className="surface surface-pad">
      <CardHeader view={view} />
      <FilesRead view={view} />

      <div className="mt-5 grid grid-cols-[1ch_6ch_minmax(0,1fr)] items-baseline gap-x-2.5 gap-y-1.5">
        <LedgerRow sign="" value={counts.links + view.unsupported_count} label="saved posts" />
        <LedgerRow sign="−" value={counts.duplicate} label="already in Sift" />
        <LedgerRow
          sign="−"
          value={view.unsupported_count}
          label="links Sift can't read"
          note={view.unsupported_count ? <UnreadableLinks urls={view.unsupported_sample} /> : undefined}
        />
        <div className="col-span-2 col-start-1 h-px bg-graphite/70" />
        <div />
        <LedgerRow sign="" value={counts.found} label="new, newest first" strong />
      </div>

      {counts.found === 0 ? (
        <p className="mt-5 text-silt">Everything in this export is already in Sift.</p>
      ) : (
        <>
          <fieldset className="mt-6 grid grid-cols-4 gap-2.5 max-[700px]:grid-cols-2">
            <legend className="sr-only">How many to import</legend>
            {view.options.map((option) => (
              <OptionCard
                key={option.limit ?? "all"}
                name={group}
                title={option.limit === null ? `All ${option.estimate.posts}` : `Newest ${option.limit}`}
                estimate={option.estimate}
                tokens={view.per_post.tokens}
                checked={choice.kind === "option" && choice.limit === option.limit}
                onSelect={() => setChoice({ kind: "option", limit: option.limit })}
              />
            ))}
            <CustomCard
              name={group}
              importId={view.id}
              value={custom}
              max={counts.found}
              tokens={view.per_post.tokens}
              checked={choice.kind === "custom"}
              onSelect={() => setChoice({ kind: "custom" })}
              onChange={(n) => {
                setCustom(n);
                setChoice({ kind: "custom" });
              }}
            />
          </fieldset>
          <p className="mt-3 max-w-[72ch] text-caption text-silt">
            Posts go to Instagram from your secondary account one at a time: one every{" "}
            {formatGap(view.pace.gap_seconds)} on average, at most {view.pace.daily_cap} a day. A link you paste waits
            behind one imported post at most. The import pauses itself if downloads keep failing.
            {!!view.per_post.usd && ` Each post costs about ${formatPerPost(view.per_post.usd)}.`}
          </p>
        </>
      )}

      <div className="mt-5 flex gap-2">
        {view.actions.includes("start") && (
          <Button variant="primary" disabled={pending || posts === 0} onClick={() => run("start", limit)}>
            {limit === null ? `Import all ${posts}` : `Import the newest ${posts}`}
          </Button>
        )}
        {view.actions.includes("cancel") && (
          <Button disabled={pending} onClick={() => run("cancel")}>
            Discard
          </Button>
        )}
      </div>
    </section>
  );
}

function FilesRead({ view }: { view: Import }): JSX.Element {
  return (
    <>
      <FileList label="Read" files={view.files_read} />
      {view.files_skipped_large.length > 0 && (
        <FileList label="Skipped" files={view.files_skipped_large} note="(too large)" />
      )}
      {view.files_skipped_budget.length > 0 && (
        <FileList label="Not read" files={view.files_skipped_budget} note="(over the 256 MB total)" />
      )}
    </>
  );
}

function FileList({ label, files, note }: { label: string; files: string[]; note?: string }): JSX.Element {
  return (
    <div className="mt-2 flex gap-2 text-caption text-silt">
      <span className="shrink-0">{label}</span>
      <ul className="min-w-0">
        {files.map((file) => (
          <li key={file} className="truncate">
            <span className="font-mono">{file}</span>
            {note && ` ${note}`}
          </li>
        ))}
      </ul>
    </div>
  );
}

function LedgerRow({
  sign,
  value,
  label,
  note,
  strong,
}: {
  sign: string;
  value: number;
  label: string;
  note?: JSX.Element | string;
  strong?: boolean;
}): JSX.Element {
  return (
    <>
      <span aria-hidden className="text-right font-mono text-silt">
        {sign}
      </span>
      <span className={cn("text-right font-mono tabular-nums", strong ? "text-[17px] text-graphite" : "text-ink-soft")}>
        {value}
      </span>
      <span className={cn("flex min-w-0 flex-wrap items-baseline gap-x-3", strong && "font-semibold")}>
        <span>{label}</span>
        {note && <span className="font-normal text-caption text-silt">{note}</span>}
      </span>
    </>
  );
}

function UnreadableLinks({ urls }: { urls: string[] }): JSX.Element {
  return (
    <details className="inline">
      <summary className="inline cursor-pointer list-none py-3 underline underline-offset-2 marker:hidden">
        Show
      </summary>
      <ul className="mt-1 max-w-full">
        {urls.map((url) => (
          <li key={url} className="truncate font-mono">
            {url}
          </li>
        ))}
      </ul>
    </details>
  );
}

function priceOf(estimate: Estimate, tokens: number): string {
  return estimate.usd === null ? `${(tokens / 1000).toFixed(1)}k tokens a post` : formatUsd(estimate.usd);
}

const cardClass =
  "flex cursor-pointer flex-col items-start surface px-4 py-3 text-left transition-colors hover:bg-hover has-checked:border-graphite has-checked:shadow-[inset_0_0_0_1px_var(--graphite)] has-focus-visible:outline-2 has-focus-visible:outline-graphite has-focus-visible:outline-offset-2";

function OptionCard({
  name,
  title,
  estimate,
  tokens,
  checked,
  onSelect,
}: {
  name: string;
  title: string;
  estimate: Estimate;
  tokens: number;
  checked: boolean;
  onSelect: () => void;
}): JSX.Element {
  return (
    <label className={cardClass}>
      <input type="radio" name={name} checked={checked} onChange={onSelect} className="sr-only" />
      <span className="font-semibold">{title}</span>
      <span className="mt-1 font-display text-[20px] leading-7">{priceOf(estimate, tokens)}</span>
      <span className="text-caption text-silt">about {formatDuration(estimate.seconds)}</span>
    </label>
  );
}

function CustomCard({
  name,
  importId,
  value,
  max,
  tokens,
  checked,
  onSelect,
  onChange,
}: {
  name: string;
  importId: number;
  value: number;
  max: number;
  tokens: number;
  checked: boolean;
  onSelect: () => void;
  onChange: (n: number) => void;
}): JSX.Element {
  const estimate = useImportEstimate(importId, Math.min(value, max));
  return (
    <label className={cardClass}>
      <input type="radio" name={name} checked={checked} onChange={onSelect} className="sr-only" />
      <span className="flex items-baseline gap-1.5 font-semibold">
        Newest
        <input
          aria-label="Import the newest this many posts"
          type="number"
          inputMode="numeric"
          min={1}
          max={max}
          value={value}
          onFocus={onSelect}
          onChange={(event) => onChange(Math.max(0, Math.floor(Number(event.target.value) || 0)))}
          className="w-[6ch] rounded-md border border-mesh bg-sheet px-1.5 py-0.5 font-mono text-[13px] outline-none focus-visible:border-graphite max-[700px]:h-9 max-[700px]:text-base"
        />
      </span>
      <span className="mt-1 font-display text-[20px] leading-7">{estimate ? priceOf(estimate, tokens) : "…"}</span>
      <span className="text-caption text-silt">
        {estimate ? `about ${formatDuration(estimate.seconds)}` : "pricing"}
      </span>
    </label>
  );
}

function useNow(ms: number): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), ms);
    return () => clearInterval(timer);
  }, [ms]);
  return now;
}

export function holdText(view: Pick<Import, "hold" | "hold_until">, now: Date, timezone: string): string | null {
  if (view.hold === null) return null;
  const until =
    view.hold_until === null
      ? null
      : view.hold === "daily_cap"
        ? formatMoment(view.hold_until, timezone)
        : formatCountdown(view.hold_until, now);
  return HOLDS[view.hold](until);
}

export function ImportProgress({ view }: { view: Import }): JSX.Element {
  const { timezone } = useStatus();
  const now = useNow(1000);
  const { run, pending } = useImportActionRunner(view);
  const { done, total } = progress(view);
  const reason = view.pause_reason ? PAUSE_REASONS[view.pause_reason] : null;
  const { counts, remaining } = view;
  const hold = holdText(view, now, timezone);
  return (
    <section aria-label={`Import ${view.filename}`} className="surface surface-pad">
      <CardHeader view={view} tone={reason?.alarm ? "alarm" : undefined} />
      <div className="mt-3 flex items-baseline justify-between gap-4">
        <span className="font-[560]">
          <span className="font-mono">{done}</span> of <span className="font-mono">{total}</span> sent to Sift
        </span>
        {hold && <span className="text-caption text-silt">{hold}</span>}
      </div>
      <div
        role="progressbar"
        aria-label="Posts imported"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={done}
        className="mt-2.5 h-0.5 rounded-full bg-mesh"
      >
        <div className="h-full rounded-full bg-graphite" style={{ width: `${total ? (done / total) * 100 : 0}%` }} />
      </div>
      <p className="mt-2.5 flex flex-wrap gap-x-3.5 text-caption text-silt">
        <span>
          <span className="font-mono text-graphite">{counts.kept}</span> kept
        </span>
        <span>
          <span className="font-mono text-graphite">{counts.archived}</span> archived
        </span>
        <span>
          <span className={cn("font-mono", counts.failed ? "text-alarm" : "text-graphite")}>{counts.failed}</span>{" "}
          failed
        </span>
        {counts.in_progress > 0 && (
          <span>
            <span className="font-mono text-graphite">{counts.in_progress}</span> in progress
          </span>
        )}
      </p>
      {view.current && (
        <p className="mt-1.5 text-caption text-silt">
          Now:{" "}
          <Link
            to="/items/$itemId"
            params={{ itemId: view.current.item_id }}
            className="py-3 text-graphite underline underline-offset-2"
          >
            post #{view.current.item_id}
          </Link>{" "}
          · {view.current.state_label}
        </p>
      )}
      {remaining && remaining.posts > 0 && (
        <p className="mt-1.5 text-caption text-silt">
          About {formatDuration(remaining.seconds)}
          {remaining.usd !== null && ` and ${formatUsd(remaining.usd)}`} to go
        </p>
      )}
      {reason && (
        <p
          className={cn(
            "mt-3 rounded-md px-3 py-2 text-[13px]",
            reason.alarm ? "bg-alarm-wash text-graphite" : "bg-pan text-ink-soft",
          )}
        >
          {reason.text}
        </p>
      )}
      <div className="mt-4 flex gap-2">
        {(["pause", "resume", "cancel"] as const)
          .filter((action) => view.actions.includes(action))
          .map((action) => (
            <Button
              key={action}
              size="sm"
              variant={action === "resume" ? "primary" : "secondary"}
              disabled={pending}
              onClick={() => run(action)}
            >
              {IMPORT_ACTIONS[action].label}
            </Button>
          ))}
      </div>
    </section>
  );
}

function ImportSummary({ view }: { view: Import }): JSX.Element {
  const { timezone } = useStatus();
  const { counts } = view;
  return (
    <section
      aria-label={`Import ${view.filename}`}
      className="flex flex-wrap items-baseline gap-x-4 gap-y-1 rounded-lg border border-mesh px-4 py-3 text-caption text-silt"
    >
      <span className="font-mono">{formatDay(view.created_at, timezone)}</span>
      <span className="min-w-0 truncate font-mono text-graphite">{view.filename}</span>
      <span>{IMPORT_PHASES[view.phase]}</span>
      <span>
        <span className="font-mono text-graphite">{counts.kept}</span> kept of{" "}
        <span className="font-mono text-graphite">{counts.released}</span> imported
      </span>
      {counts.failed > 0 && (
        <span>
          <span className="font-mono text-alarm">{counts.failed}</span> failed
        </span>
      )}
    </section>
  );
}

export function ImportBanner({ view }: { view: Import }): JSX.Element {
  const { timezone } = useStatus();
  const now = useNow(1000);
  const { done, total } = progress(view);
  const reason = view.pause_reason ? PAUSE_REASONS[view.pause_reason] : null;
  const hold = view.phase === "paused" ? null : holdText(view, now, timezone);
  return (
    <Link
      to="/import"
      className="surface mb-5 flex min-h-11 items-center gap-3.5 px-4 py-3 text-[13px] hover:bg-hover active:bg-hover"
    >
      <span className={cn("shrink-0 font-semibold", reason?.alarm ? "text-alarm" : "text-graphite")}>
        {view.phase === "paused" ? "Import paused" : "Importing saved posts"}
      </span>
      <span aria-hidden className="h-0.5 w-[88px] shrink-0 rounded-full bg-mesh max-[700px]:hidden">
        <span
          className="block h-full rounded-full bg-graphite"
          style={{ width: `${total ? (done / total) * 100 : 0}%` }}
        />
      </span>
      <span className="shrink-0 font-mono text-silt">
        {done} of {total}
      </span>
      {hold && <span className="min-w-0 truncate text-silt max-[700px]:hidden">{hold}</span>}
      <span className="ml-auto shrink-0 font-medium text-graphite">Details</span>
    </Link>
  );
}
