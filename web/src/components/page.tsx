import type { JSX, ReactNode } from "react";
import { useStatus } from "@/api";
import { NoticeBanner } from "@/components/notice-banner";
import { cn } from "@/lib/utils";

export function Page({ children, wide }: { children: ReactNode; wide?: boolean }): JSX.Element {
  const { notice } = useStatus();
  return (
    <div className={cn("w-full", wide ? "max-w-[928px]" : "max-w-[848px]")}>
      <NoticeBanner notice={notice} />
      {children}
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  aside,
}: {
  title: string;
  subtitle?: ReactNode;
  aside?: ReactNode;
}): JSX.Element {
  return (
    <header className="mb-5 flex items-end justify-between gap-6">
      <div>
        <h1 className="font-display font-[640] text-page max-[700px]:text-[28px] max-[700px]:leading-8">{title}</h1>
        {subtitle && <p className="mt-1.5 text-silt">{subtitle}</p>}
      </div>
      {aside && <div className="shrink-0 pb-0.5 max-[700px]:hidden">{aside}</div>}
    </header>
  );
}

export function Empty({ title, children }: { title: string; children: ReactNode }): JSX.Element {
  return (
    <div className="rounded-lg border border-mesh border-dashed px-6 py-12 text-center">
      <p className="font-semibold">{title}</p>
      <p className="mx-auto mt-1 max-w-[46ch] text-silt">{children}</p>
    </div>
  );
}
