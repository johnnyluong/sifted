import { type LucideIcon, Monitor, Moon, Sun } from "lucide-react";
import { type JSX, useId } from "react";
import { Choice } from "@/components/ui/field";
import { setTheme, THEMES, type Theme, useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

const THEME_CHOICES: Record<Theme, { label: string; icon: LucideIcon }> = {
  system: { label: "System", icon: Monitor },
  light: { label: "Light", icon: Sun },
  dark: { label: "Dark", icon: Moon },
};

export function ThemePicker({ className }: { className?: string }): JSX.Element {
  const theme = useTheme();
  const name = useId();
  return (
    <fieldset className={cn("flex flex-wrap gap-1.5", className)}>
      <legend className="sr-only">Theme</legend>
      {THEMES.map((t) => {
        const choice = THEME_CHOICES[t];
        return (
          <Choice key={t} name={name} checked={theme === t} onChange={() => setTheme(t)} className="gap-1.5 px-3">
            <choice.icon aria-hidden className="size-3.5" />
            {choice.label}
          </Choice>
        );
      })}
    </fieldset>
  );
}
