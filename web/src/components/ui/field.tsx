import { ChevronDown } from "lucide-react";
import { type ComponentProps, type JSX, type ReactNode, useLayoutEffect, useRef } from "react";
import { cn } from "@/lib/utils";

const field =
  "w-full min-w-0 rounded-md border border-mesh bg-sheet text-graphite outline-none transition-colors placeholder:text-dust focus-visible:border-graphite max-[700px]:text-base focus-visible:outline-none aria-invalid:border-alarm";

export function Input({ className, ...props }: ComponentProps<"input">): JSX.Element {
  return <input className={cn(field, "h-9 px-3 max-[700px]:h-11 max-[700px]:px-4", className)} {...props} />;
}

export function Textarea({ className, ...props }: ComponentProps<"textarea">): JSX.Element {
  return (
    <textarea
      className={cn(field, "field-sizing-content min-h-24 px-3 py-2.5 leading-[22px] max-[700px]:px-4", className)}
      {...props}
    />
  );
}

/** A one-line text field that wraps a long value onto more lines instead of scrolling it out of view. */
export function LineInput({
  className,
  value,
  onChange,
  onKeyDown,
  ...props
}: Omit<ComponentProps<"textarea">, "value" | "rows"> & { value: string }): JSX.Element {
  const ref = useRef<HTMLTextAreaElement>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: the height follows the value.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || CSS.supports("field-sizing", "content")) return;
    const fit = () => {
      el.style.height = "auto";
      el.style.height = `${el.scrollHeight + el.offsetHeight - el.clientHeight}px`;
    };
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [value]);
  return (
    <textarea
      ref={ref}
      rows={1}
      value={value}
      onChange={(e) => {
        if (/[\r\n]/.test(e.target.value)) e.target.value = e.target.value.replace(/\s*[\r\n]+\s*/g, " ");
        onChange?.(e);
      }}
      onKeyDown={(e) => {
        onKeyDown?.(e);
        if (e.key !== "Enter" || e.defaultPrevented || e.nativeEvent.isComposing) return;
        e.preventDefault();
        e.currentTarget.form?.requestSubmit();
      }}
      className={cn(
        field,
        "field-sizing-content block resize-none overflow-hidden px-3 py-1.5 leading-[22px] max-[700px]:px-4 max-[700px]:py-2.5",
        className,
      )}
      {...props}
    />
  );
}

export function Select({ className, ...props }: ComponentProps<"select">): JSX.Element {
  return (
    <span className={cn("relative inline-flex", className)}>
      <select
        className={cn(field, "h-9 cursor-pointer appearance-none pr-8 pl-3 max-[700px]:h-11 max-[700px]:pl-4")}
        {...props}
      />
      <ChevronDown
        aria-hidden
        className="pointer-events-none absolute top-1/2 right-2.5 size-3.5 -translate-y-1/2 text-silt"
      />
    </span>
  );
}

export function Label({ className, ...props }: ComponentProps<"label">): JSX.Element {
  // biome-ignore lint/a11y/noLabelWithoutControl: callers pass htmlFor or nest the control.
  return <label className={cn("mb-1.5 block font-[520] text-[13px] text-ink-soft", className)} {...props} />;
}

const choiceClass =
  "inline-flex min-h-9 cursor-pointer items-center rounded-full border border-mesh px-3.5 text-[13px] text-ink-soft transition-colors hover:bg-pan-hover has-checked:border-graphite has-checked:bg-sheet has-checked:font-[560] has-checked:text-graphite has-focus-visible:outline-2 has-focus-visible:outline-graphite has-focus-visible:outline-offset-2 max-[700px]:min-h-11 max-[700px]:text-[15px]";

export function Choice({
  className,
  children,
  ...input
}: Omit<ComponentProps<"input">, "className" | "children"> & { className?: string; children: ReactNode }): JSX.Element {
  return (
    <label className={cn(choiceClass, className)}>
      <input type="radio" {...input} className="sr-only" />
      {children}
    </label>
  );
}

export function FieldError({ className, ...props }: ComponentProps<"p">): JSX.Element {
  return <p role="alert" className={cn("text-[13px] text-alarm", className)} {...props} />;
}
