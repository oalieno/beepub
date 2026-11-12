<script lang="ts">
  /** A book's actions as the items of a DropdownMenu (see BookActions). */
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu";
  import type { BookAction } from "./BookActions.svelte";

  let {
    groups,
    separated = false,
  }: {
    groups: BookAction[][];
    /** The menu has items of its own above: set the first group apart
     *  from them too. */
    separated?: boolean;
  } = $props();
</script>

{#each groups as group, i}
  {#if i > 0 || separated}
    <DropdownMenu.Separator />
  {/if}
  {#each group as action (action.key)}
    <DropdownMenu.Item
      variant={action.destructive ? "destructive" : "default"}
      disabled={action.disabled}
      onclick={action.run}
    >
      <action.icon size={14} class={action.tone ?? ""} />
      {action.label}
    </DropdownMenu.Item>
  {/each}
{/each}
