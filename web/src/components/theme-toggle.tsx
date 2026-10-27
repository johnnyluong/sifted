import { Monitor, Moon, Sun } from "lucide-react";
import type { JSX } from "react";
import { setTheme, THEMES, useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

const THEME_ICONS = { system: Monitor, light: Sun, dark: Moon } as const;

export function ThemeToggle({ className }: { className?: string }): JSX.Element {
  const theme = useTheme();
  const next = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length] ?? "system";
  const Icon = THEME_ICONS[theme];
  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      className={cn(
        "flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-1.5 text-caption text-silt hover:bg-pan-hover hover:text-graphite",
        className,
      )}
      aria-label={`Theme: ${theme}. Switch to ${next}.`}
    >
      <Icon aria-hidden className="size-3.5" />
      <span className="capitalize">{theme}</span>
    </button>
  );
}
