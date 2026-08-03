import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";

const OPTIONS: Array<{ value: number; label: string }> = [
  { value: 0, label: "Hold" },
  { value: 10, label: "10s" },
  { value: 30, label: "30s" },
  { value: 60, label: "1m" },
  { value: 300, label: "5m" },
];

interface Props {
  value: number;
  onChange: (seconds: number) => void;
  className?: string;
}

/** Duration for presets, patterns and pulse loops. `Hold` (0) means "until stopped". */
export function DurationPicker({ value, onChange, className }: Props) {
  return (
    <ToggleGroup
      type="single"
      value={String(value)}
      onValueChange={(next) => {
        if (next) onChange(Number(next));
      }}
      className={cn("w-full", className)}
      aria-label="Duration"
    >
      {OPTIONS.map((option) => (
        <ToggleGroupItem
          key={option.value}
          value={String(option.value)}
          className="flex-1"
          title={option.value === 0 ? "Run until stopped" : `Run for ${option.label}`}
        >
          {option.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
