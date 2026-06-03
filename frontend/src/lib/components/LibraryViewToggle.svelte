<script lang="ts">
  import { BookCopy, Layers } from "@lucide/svelte";
  import * as m from "$lib/paraglide/messages.js";

  let {
    libraryId,
    active,
  }: {
    libraryId: string;
    active: "books" | "series";
  } = $props();
</script>

<div class="inline-flex gap-1 bg-muted rounded-lg p-1">
  <a
    href="/libraries/{libraryId}"
    class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors {active ===
    'books'
      ? 'bg-background text-foreground shadow-sm'
      : 'text-muted-foreground hover:text-foreground'}"
  >
    <BookCopy size={15} />
    {m.library_tab_books()}
  </a>
  <a
    href="/libraries/{libraryId}/series"
    class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors {active ===
    'series'
      ? 'bg-background text-foreground shadow-sm'
      : 'text-muted-foreground hover:text-foreground'}"
  >
    <Layers size={15} />
    {m.library_tab_series()}
  </a>
</div>
