<script lang="ts">
  import type { Snippet } from "svelte";
  import { page } from "$app/state";

  let { children }: { children: Snippet } = $props();
</script>

<!-- A reader page holds one book's state: another book is another page,
     even when only the id in the URL changed. -->
{#key page.params.id}
  {@render children()}
{/key}
