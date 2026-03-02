<script lang="ts">
  import { goto } from '$app/navigation';
  import type { BookOut } from '$lib/types';
  import { BookOpen } from '@lucide/svelte';

  let { book }: { book: BookOut } = $props();
</script>

<button
  class="text-left w-full group"
  onclick={() => goto(`/books/${book.id}`)}
>
  <!-- Cover with book shadow -->
  <div class="aspect-[2/3] rounded-lg overflow-hidden book-shadow book-shadow-hover transition-all duration-300 mb-3">
    {#if book.cover_path}
      <img
        src="/covers/{book.id}.jpg"
        alt="{book.display_title} cover"
        class="w-full h-full object-cover"
        loading="lazy"
      />
    {:else}
      <div class="w-full h-full bg-secondary flex flex-col items-center justify-center gap-2 p-4">
        <BookOpen class="text-muted-foreground/30" size={36} />
        <span class="text-muted-foreground/60 text-xs text-center line-clamp-3">{book.display_title ?? 'Untitled'}</span>
      </div>
    {/if}
  </div>

  <!-- Info below cover — fixed height so grid rows align -->
  <div class="min-h-[3rem]">
    <h3 class="font-medium text-sm line-clamp-2 leading-snug text-foreground group-hover:text-primary transition-colors">{book.display_title ?? 'Untitled'}</h3>
    <p class="text-muted-foreground text-xs mt-0.5 line-clamp-1">{(book.display_authors ?? []).join(', ') || '\u00A0'}</p>
  </div>
</button>
