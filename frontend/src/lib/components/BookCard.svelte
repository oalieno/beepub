<script lang="ts">
  import { goto } from '$app/navigation';
  import type { BookOut } from '$lib/types';
  import { BookOpen } from 'lucide-svelte';

  export let book: BookOut;
</script>

<button
  class="bg-gray-800 rounded-lg overflow-hidden hover:bg-gray-750 hover:ring-2 hover:ring-amber-500 transition-all text-left w-full group"
  on:click={() => goto(`/books/${book.id}`)}
>
  <!-- Cover -->
  <div class="aspect-[2/3] bg-gray-700 relative overflow-hidden">
    {#if book.cover_path}
      <img
        src="/covers/{book.id}.jpg"
        alt="{book.display_title} cover"
        class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
        loading="lazy"
      />
    {:else}
      <div class="w-full h-full flex flex-col items-center justify-center gap-2 p-4">
        <BookOpen class="text-gray-500" size={40} />
        <span class="text-gray-500 text-xs text-center line-clamp-3">{book.display_title ?? 'Untitled'}</span>
      </div>
    {/if}
  </div>

  <!-- Info -->
  <div class="p-3">
    <h3 class="font-semibold text-sm line-clamp-2 leading-tight">{book.display_title ?? 'Untitled'}</h3>
    {#if (book.display_authors ?? []).length > 0}
      <p class="text-gray-400 text-xs mt-1 line-clamp-1">{(book.display_authors ?? []).join(', ')}</p>
    {/if}
  </div>
</button>
