<script lang="ts">
  import {
    Bookmark,
    BookOpenCheck,
    CircleCheck,
    CircleX,
    BookMarked,
  } from "@lucide/svelte";
  import * as Select from "$lib/components/ui/select";
  import DatePicker from "$lib/components/DatePicker.svelte";
  import type { ReadingStatus, InteractionOut } from "$lib/types";

  let {
    interaction,
    saving = false,
    onstatuschange,
    ondatechange,
  }: {
    interaction: InteractionOut | null;
    saving?: boolean;
    onstatuschange: (status: ReadingStatus | null) => void;
    ondatechange: (field: "started_at" | "finished_at", value: string) => void;
  } = $props();

  const READING_STATUS_OPTIONS: {
    value: ReadingStatus;
    label: string;
    icon: typeof Bookmark;
  }[] = [
    { value: "want_to_read", label: "Want to Read", icon: Bookmark },
    {
      value: "currently_reading",
      label: "Currently Reading",
      icon: BookOpenCheck,
    },
    { value: "read", label: "Read", icon: CircleCheck },
    { value: "did_not_finish", label: "Did Not Finish", icon: CircleX },
  ];

  const CLEAR_STATUS_VALUE = "__clear_status__";

  function handleChange(value: string) {
    if (value === CLEAR_STATUS_VALUE) {
      onstatuschange(null);
      return;
    }
    onstatuschange(value as ReadingStatus);
  }
</script>

<div class="mt-5">
  <Select.Root
    type="single"
    value={interaction?.reading_status ?? undefined}
    onValueChange={handleChange}
    disabled={saving}
  >
    <Select.Trigger
      class="w-full md:w-auto !h-10 rounded-full bg-white md:text-sm text-base justify-center md:justify-start {interaction?.reading_status ===
      'read'
        ? 'text-green-600 border-green-600/30'
        : ''}"
    >
      {#if interaction?.reading_status}
        {@const current = READING_STATUS_OPTIONS.find(
          (o) => o.value === interaction?.reading_status,
        )}
        {#if current}
          <current.icon
            size={16}
            class={interaction?.reading_status === "read"
              ? "text-green-600"
              : ""}
          />
          {current.label}
        {/if}
      {:else}
        Set status
      {/if}
    </Select.Trigger>
    <Select.Content align="start">
      <Select.Item value={CLEAR_STATUS_VALUE}>
        {#snippet children()}
          <BookMarked size={14} class="text-muted-foreground" />
          <span>Clear status</span>
        {/snippet}
      </Select.Item>
      <Select.Separator />
      {#each READING_STATUS_OPTIONS as opt}
        <Select.Item value={opt.value}>
          {#snippet children({ selected })}
            <opt.icon
              size={14}
              class={opt.value === "read" && selected
                ? "text-green-600"
                : "text-muted-foreground"}
            />
            <span>{opt.label}</span>
          {/snippet}
        </Select.Item>
      {/each}
    </Select.Content>
  </Select.Root>
  {#if interaction?.reading_status === "read" || interaction?.reading_status === "currently_reading"}
    <div
      class="mt-2 flex items-center justify-center md:justify-start gap-3 text-sm text-muted-foreground"
    >
      <span class="flex items-center gap-1.5">
        Started
        <DatePicker
          variant="text"
          value={interaction?.started_at ?? null}
          onchange={(v) => ondatechange("started_at", v ?? "")}
        />
      </span>
      {#if interaction?.reading_status === "read"}
        <span class="flex items-center gap-1.5">
          Finished
          <DatePicker
            variant="text"
            value={interaction?.finished_at ?? null}
            onchange={(v) => ondatechange("finished_at", v ?? "")}
          />
        </span>
      {/if}
    </div>
  {/if}
</div>
