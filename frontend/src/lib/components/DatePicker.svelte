<script lang="ts">
  import { CalendarDate, type DateValue } from "@internationalized/date";
  import { CalendarIcon } from "@lucide/svelte";
  import { Calendar } from "$lib/components/ui/calendar";
  import * as Popover from "$lib/components/ui/popover";

  let {
    value = $bindable<string | null>(null),
    onchange,
    placeholder = "Pick a date",
  }: {
    value?: string | null;
    onchange?: (value: string | null) => void;
    placeholder?: string;
  } = $props();

  let open = $state(false);

  let calendarValue = $derived.by(() => {
    if (!value) return undefined;
    const [y, m, d] = value.split("-").map(Number);
    return new CalendarDate(y, m, d);
  });

  function handleSelect(v: DateValue | undefined) {
    if (v) {
      const dateStr = `${v.year}-${String(v.month).padStart(2, "0")}-${String(v.day).padStart(2, "0")}`;
      value = dateStr;
      onchange?.(dateStr);
    } else {
      value = null;
      onchange?.(null);
    }
    open = false;
  }

  function formatDisplay(v: string | null): string {
    if (!v) return placeholder;
    const [y, m, d] = v.split("-");
    return `${y}/${m}/${d}`;
  }
</script>

<Popover.Root bind:open>
  <Popover.Trigger>
    <button
      type="button"
      class="flex h-9 items-center gap-2 rounded-full border border-input bg-white px-3 py-1 text-sm shadow-xs transition-[color,box-shadow] outline-none select-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] {value
        ? 'text-foreground'
        : 'text-muted-foreground'}"
    >
      <CalendarIcon size={14} class="text-muted-foreground" />
      {formatDisplay(value)}
    </button>
  </Popover.Trigger>
  <Popover.Content class="w-auto p-0" align="start">
    <Calendar
      type="single"
      value={calendarValue}
      onValueChange={handleSelect}
      captionLayout="dropdown"
    />
  </Popover.Content>
</Popover.Root>
