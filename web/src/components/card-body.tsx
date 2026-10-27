import { ArrowUpRight } from "lucide-react";
import type { JSX, ReactNode } from "react";
import type { Card, CardOf } from "@/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function CardBody({ card }: { card: Card }): JSX.Element | null {
  switch (card.item_type) {
    case "place":
      return <PlaceBody details={card.details} />;
    case "recipe":
      return <RecipeBody details={card.details} />;
    case "playbook":
      return <PlaybookBody details={card.details} />;
    case "idea":
      return <IdeaBody details={card.details} />;
    case "product":
      return <ProductBody details={card.details} />;
    case "other":
      return <OtherBody details={card.details} />;
    default:
      return unreachable(card);
  }
}

function unreachable(card: never): never {
  throw new Error(`unknown card type: ${JSON.stringify(card)}`);
}

type Details<T extends Card["item_type"]> = { details: CardOf<T>["details"] };

export function Section({
  title,
  className,
  children,
}: {
  title: string;
  className?: string;
  children: ReactNode;
}): JSX.Element {
  return (
    <section className={cn("mt-7 first:mt-0", className)}>
      <h2 className="mb-2 font-mono text-micro text-silt uppercase tracking-[0.04em]">{title}</h2>
      {children}
    </section>
  );
}

export function Facts({ rows }: { rows: [string, ReactNode][] }): JSX.Element | null {
  const shown = rows.filter(([, value]) => value !== null && value !== undefined && value !== false && value !== "");
  if (shown.length === 0) return null;
  return (
    <dl className="grid grid-cols-[96px_minmax(0,1fr)] gap-x-3 gap-y-2">
      {shown.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-silt">{label}</dt>
          <dd className="wrap-anywhere">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Bullets({ items }: { items: string[] }): JSX.Element {
  return (
    <ul className="space-y-1.5 text-ink-soft">
      {items.map((item, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: LLM text can repeat, and the list never reorders.
        <li key={i} className="flex gap-2.5">
          <span aria-hidden className="text-dust">
            ·
          </span>
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

function Steps({ items }: { items: string[] }): JSX.Element {
  return (
    <ol className="space-y-2.5 text-ink-soft">
      {items.map((item, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: a fixed sequence, where the same text can appear twice.
        <li key={i} className="flex gap-3">
          <span className="w-5 shrink-0 pt-px text-right font-mono text-caption text-silt">{i + 1}</span>
          <span>{item}</span>
        </li>
      ))}
    </ol>
  );
}

function Prose({ children }: { children: ReactNode }): JSX.Element {
  return <p className="max-w-[62ch] text-ink-soft">{children}</p>;
}

function OutLink({ href, children }: { href: string; children: ReactNode }): JSX.Element {
  return (
    <Button asChild className="mt-6">
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
        <ArrowUpRight aria-hidden />
      </a>
    </Button>
  );
}

function PlaceBody({ details: d }: Details<"place">): JSX.Element {
  const area = [d.neighborhood, d.city].filter(Boolean).join(", ");
  return (
    <>
      <Section title="Place">
        <Facts
          rows={[
            ["Name", d.name],
            ["Kind", d.kind],
            ["Area", area],
            ["Address", d.address],
            ["Price", d.price_hint],
          ]}
        />
      </Section>
      {d.why_notable && (
        <Section title="Why it's notable">
          <Prose>{d.why_notable}</Prose>
        </Section>
      )}
      {d.what_to_order_or_do.length > 0 && (
        <Section title="What to order or do">
          <Bullets items={d.what_to_order_or_do} />
        </Section>
      )}
      <OutLink href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(d.maps_query)}`}>
        Open in Maps
      </OutLink>
    </>
  );
}

function RecipeBody({ details: d }: Details<"recipe">): JSX.Element {
  return (
    <>
      <Section title="Recipe">
        <Facts
          rows={[
            ["Dish", d.dish],
            ["Time", d.total_time],
          ]}
        />
      </Section>
      {d.ingredients.length > 0 && (
        <Section title="Ingredients">
          <ul className="max-w-[440px] divide-y divide-mesh">
            {d.ingredients.map((ing, i) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: LLM text can repeat, and the list never reorders.
              <li key={i} className="flex justify-between gap-4 py-1.5">
                <span>{ing.name}</span>
                <span className="font-mono text-caption text-silt">{ing.amount}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {d.steps.length > 0 && (
        <Section title="Steps">
          <Steps items={d.steps} />
        </Section>
      )}
      {d.notes.length > 0 && (
        <Section title="Notes">
          <Bullets items={d.notes} />
        </Section>
      )}
    </>
  );
}

function PlaybookBody({ details: d }: Details<"playbook">): JSX.Element {
  return (
    <>
      <Section title="Playbook">
        <Prose>{d.goal}</Prose>
      </Section>
      {d.steps.length > 0 && (
        <Section title="Steps">
          <Steps items={d.steps} />
        </Section>
      )}
      {d.tools.length > 0 && (
        <Section title="Tools">
          <ul className="flex flex-wrap gap-1.5">
            {d.tools.map((tool, i) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: LLM text can repeat, and the list never reorders.
              <li key={i} className="rounded-sm border border-mesh bg-sheet px-2 py-0.5 text-[13px]">
                {tool}
              </li>
            ))}
          </ul>
        </Section>
      )}
      {d.examples.length > 0 && (
        <Section title="Examples">
          <Bullets items={d.examples} />
        </Section>
      )}
      {d.caveats.length > 0 && (
        <Section title="Caveats">
          <Bullets items={d.caveats} />
        </Section>
      )}
    </>
  );
}

function IdeaBody({ details: d }: Details<"idea">): JSX.Element {
  return (
    <>
      <Section title="Idea">
        <Prose>{d.core_idea}</Prose>
      </Section>
      {d.how_to_apply && (
        <Section title="How to apply it">
          <Prose>{d.how_to_apply}</Prose>
        </Section>
      )}
      {d.creator && (
        <Section title="From">
          <Prose>{d.creator}</Prose>
        </Section>
      )}
    </>
  );
}

function ProductBody({ details: d }: Details<"product">): JSX.Element {
  const link = d.link && /^https?:\/\//i.test(d.link) ? d.link : null;
  return (
    <>
      <Section title="Product">
        <Facts
          rows={[
            ["Name", d.name],
            ["What it is", d.what_it_is],
            ["Price", d.price],
          ]}
        />
      </Section>
      {link && <OutLink href={link}>Open link</OutLink>}
    </>
  );
}

function OtherBody({ details: d }: Details<"other">): JSX.Element | null {
  if (d.key_points.length === 0) return null;
  return (
    <Section title="Key points">
      <Bullets items={d.key_points} />
    </Section>
  );
}
