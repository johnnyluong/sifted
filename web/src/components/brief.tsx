import { Link } from "@tanstack/react-router";
import { ArrowUpRight } from "lucide-react";
import type { JSX } from "react";
import type { Brief, BriefPoint, BriefSource, Citation } from "@/api";
import { Section } from "@/components/card-body";
import { Thumb } from "@/components/thumb";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { nestSources } from "@/lib/folds";
import { keyByText } from "@/lib/keys";
import { cn } from "@/lib/utils";
import { TYPES } from "@/lib/vocabulary";

type Light = (footnotes: readonly number[]) => void;

export function BriefBody({ brief, light }: { brief: Brief; light: Light }): JSX.Element {
  const byNumber = new Map(brief.sources.map((s) => [s.n, s]));
  return (
    <>
      <p className="reading text-ink-soft">{brief.overview}</p>
      {keyByText(brief.sections, (s) => s.heading).map(({ key, row: section }) => (
        <Section key={key} title={section.heading}>
          <ul className="space-y-2.5">
            {keyByText(section.points, (p) => p.text).map(({ key, row: point }) => (
              <Point key={key} point={point} sources={byNumber} light={light} />
            ))}
          </ul>
        </Section>
      ))}
    </>
  );
}

function Point({
  point,
  sources,
  light,
}: {
  point: BriefPoint;
  sources: Map<number, BriefSource>;
  light: Light;
}): JSX.Element {
  const cited = point.cites.map((c) => c.n);
  return (
    <li
      className="flex gap-2.5"
      onMouseEnter={() => light(cited)}
      onMouseLeave={() => light([])}
      onFocus={() => light(cited)}
      onBlur={() => light([])}
    >
      <span
        aria-hidden
        title={point.corroborated ? "Two or more posts say this" : undefined}
        className={cn(
          "mt-[8px] size-[7px] shrink-0 rounded-full",
          point.corroborated ? "bg-graphite" : "shadow-[inset_0_0_0_1.5px_var(--dust)]",
        )}
      />
      <span className="min-w-0 text-ink-soft">
        {point.text}
        {point.cites.map((cite) => {
          const source = sources.get(cite.n);
          return source ? <CitationMark key={cite.n} cite={cite} source={source} /> : null;
        })}
      </span>
    </li>
  );
}

function CitationMark({ cite, source }: { cite: Citation; source: BriefSource }): JSX.Element {
  return (
    <Popover>
      <PopoverTrigger
        aria-label={`Source ${cite.n}: ${source.item.title}`}
        className="relative ml-1 inline-grid h-4 min-w-4 cursor-pointer place-items-center rounded-[5px] border border-mesh px-1 align-[1px] font-mono text-[10px] text-brass leading-none hit-area-44 hover:border-brass data-[state=open]:border-brass"
      >
        {cite.n}
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[min(320px,calc(100vw-32px))]">
        <p className="font-semibold">{source.item.title}</p>
        <p className="mt-1 text-[13px] text-silt leading-[19px]">{cite.point}</p>
        <Link
          to="/items/$itemId"
          params={{ itemId: source.item.id }}
          className="mt-2 inline-flex min-h-9 items-center gap-1 text-[13px] text-graphite underline underline-offset-2"
        >
          Open post
          <ArrowUpRight aria-hidden className="size-3.5" />
        </Link>
      </PopoverContent>
    </Popover>
  );
}

export function SourceLedger({ sources, lit }: { sources: BriefSource[]; lit: ReadonlySet<number> }): JSX.Element {
  return (
    <ol className="surface overflow-hidden">
      {nestSources(sources).map(({ row, under }) => (
        <li key={row.n} className="border-mesh border-t first:border-t-0">
          <SourceRow source={row} lit={lit.has(row.n)} />
          {under.length > 0 && (
            <ol>
              {under.map((s) => (
                <li key={s.n} className="border-mesh border-t border-dashed">
                  <SourceRow source={s} lit={lit.has(s.n)} covered />
                </li>
              ))}
            </ol>
          )}
        </li>
      ))}
    </ol>
  );
}

function SourceRow({ source, lit, covered }: { source: BriefSource; lit: boolean; covered?: boolean }): JSX.Element {
  return (
    <Link
      id={`source-${source.n}`}
      to="/items/$itemId"
      params={{ itemId: source.item.id }}
      data-lit={lit || undefined}
      className={cn(
        "grid grid-cols-[20px_40px_minmax(0,1fr)] items-center gap-3 py-2.5 pr-4 pl-3 transition-colors hover:bg-hover data-[lit]:bg-hover data-[lit]:shadow-[inset_2px_0_0_var(--graphite)]",
        covered && "grid-cols-[20px_28px_minmax(0,1fr)] pl-10",
        !source.current && "opacity-60",
      )}
    >
      <span className="text-right font-mono text-caption text-brass">{source.n}</span>
      <Thumb url={source.thumbnail_url} size={covered ? 28 : 40} placeholder={<TypeIcon source={source} />} />
      <span className="min-w-0">
        <span className="block truncate font-medium">{source.item.title}</span>
        <span className="block truncate text-caption text-silt">{sourceNote(source)}</span>
      </span>
    </Link>
  );
}

function sourceNote(source: BriefSource): string {
  if (!source.current) return "No longer in this topic";
  if (source.covered_by !== null) return `Says the same as ${source.covered_by}`;
  return source.item_type ? TYPES[source.item_type].label : "Post";
}

function TypeIcon({ source }: { source: BriefSource }): JSX.Element | null {
  const Icon = source.item_type ? TYPES[source.item_type].icon : null;
  return Icon && <Icon className="size-3.5" strokeWidth={1.8} />;
}
