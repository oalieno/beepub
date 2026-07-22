<script lang="ts">
  import { Checkbox as CheckboxPrimitive } from "bits-ui";
  import { Check, Minus } from "@lucide/svelte";
  import { cn } from "$lib/utils";

  let {
    ref = $bindable(null),
    checked = $bindable(false),
    indeterminate = $bindable(false),
    class: className,
    ...restProps
  }: CheckboxPrimitive.RootProps = $props();
</script>

<CheckboxPrimitive.Root
  bind:ref
  bind:checked
  bind:indeterminate
  data-slot="checkbox"
  class={cn(
    "peer size-4 shrink-0 rounded-[4px] border border-input shadow-xs transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:border-primary data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground",
    className,
  )}
  {...restProps}
>
  {#snippet children({ checked: isChecked, indeterminate: isIndeterminate })}
    <span
      data-slot="checkbox-indicator"
      class="flex size-full items-center justify-center text-current"
    >
      {#if isIndeterminate}
        <Minus class="size-3" />
      {:else if isChecked}
        <Check class="size-3" />
      {/if}
    </span>
  {/snippet}
</CheckboxPrimitive.Root>
