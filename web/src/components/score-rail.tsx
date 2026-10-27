import { motion } from "motion/react";
import { type CSSProperties, type JSX, useEffect, useState } from "react";
import type { Decision, Item } from "@/api";

export type MarkTone = "kept" | "done" | "archived";

export type RailMark = { at: number; tone: MarkTone; overruled: boolean };

type Scored = Pick<Item, "relevance_score" | "status" | "user_override" | "threshold_decision">;

export function railMark(item: Scored): RailMark | null {
  if (item.relevance_score === null) return null;
  const tone: MarkTone = item.status === "done" ? "done" : item.status === "kept" ? "kept" : "archived";
  const overruled = item.user_override !== null && item.user_override !== item.threshold_decision;
  return { at: Math.min(100, Math.max(0, item.relevance_score)), tone, overruled };
}

export function tetherSpan(at: number, threshold: number, toward: Decision): { left: number; width: number } {
  const end = Math.min(100, Math.max(0, toward === "keep" ? threshold + 8 : threshold - 8));
  return { left: Math.min(at, end), width: Math.abs(end - at) };
}

function Tether({ at, threshold, toward }: { at: number; threshold: number; toward: Decision }): JSX.Element {
  const { left, width } = tetherSpan(at, threshold, toward);
  return <span className="rail-tether" data-toward={toward} style={{ left: `${left}%`, width: `${width}%` }} />;
}

function meterLabel(score: number, threshold: number): string {
  return `Relevance ${score} of 100, keep line ${threshold}`;
}

export function ScoreRail({ item, threshold }: { item: Item; threshold: number }): JSX.Element | null {
  const mark = railMark(item);
  if (!mark || item.relevance_score === null) return null;
  return (
    <div className="flex items-center gap-3">
      <span className="w-[22px] text-right font-mono text-caption">{item.relevance_score}</span>
      {/* biome-ignore lint/a11y/useSemanticElements: a native <meter> cannot hold the mark and the tether. */}
      <div
        className="rail"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={item.relevance_score}
        aria-label={meterLabel(item.relevance_score, threshold)}
      >
        {mark.overruled && item.user_override && (
          <Tether at={mark.at} threshold={threshold} toward={item.user_override} />
        )}
        <span className="rail-mark" data-tone={mark.tone} style={{ left: `${mark.at}%` }} />
      </div>
    </div>
  );
}

let lineDrawn = false;

export function ThresholdLine({ threshold }: { threshold: number }): JSX.Element {
  const [draw] = useState(() => !lineDrawn);
  useEffect(() => {
    lineDrawn = true;
  }, []);
  return (
    <motion.div
      className="threshold-line"
      aria-hidden
      style={{ "--threshold": threshold } as CSSProperties}
      initial={draw ? { scaleY: 0 } : false}
      animate={{ scaleY: 1 }}
      transition={{ duration: 0.42, ease: "easeOut" }}
    >
      <span className="threshold-label">{threshold}</span>
    </motion.div>
  );
}

export function verdict(item: Scored, threshold: number): string {
  if (railMark(item)?.overruled && item.user_override) {
    const chose = item.user_override === "keep" ? "kept" : "archived";
    return `You ${chose} this; the filter said ${item.threshold_decision ?? "nothing"}.`;
  }
  return `${item.threshold_decision === "keep" ? "Above" : "Below"} your line of ${threshold}`;
}

export function ScoreInstrument({ item, threshold }: { item: Item; threshold: number }): JSX.Element | null {
  const mark = railMark(item);
  if (!mark || item.relevance_score === null) return null;
  return (
    <div className="instrument">
      <div className="mt-3.5 mb-[18px] flex items-baseline">
        <span className="font-display font-light text-score">{item.relevance_score}</span>
        <span className="ml-1.5 font-mono text-caption text-silt">/ 100</span>
      </div>
      {/* biome-ignore lint/a11y/useSemanticElements: a native <meter> cannot hold the mark and the tether. */}
      <div
        className="relative mt-2.5 mb-2 h-0.5 bg-mesh"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={item.relevance_score}
        aria-label={meterLabel(item.relevance_score, threshold)}
      >
        <span
          aria-hidden
          className="absolute -top-[9px] -bottom-[9px] w-px bg-brass"
          style={{ left: `${threshold}%` }}
        />
        {mark.overruled && item.user_override && (
          <Tether at={mark.at} threshold={threshold} toward={item.user_override} />
        )}
        <motion.span
          className="rail-mark"
          data-tone={mark.tone}
          initial={{ left: "0%" }}
          animate={{ left: `${mark.at}%` }}
          transition={{ type: "spring", duration: 0.5, bounce: 0 }}
        />
      </div>
      <div aria-hidden className="relative flex justify-between font-mono text-micro text-silt">
        <span>0</span>
        <span className="absolute -translate-x-1/2 text-brass" style={{ left: `${threshold}%` }}>
          {threshold}
        </span>
        <span>100</span>
      </div>
    </div>
  );
}
