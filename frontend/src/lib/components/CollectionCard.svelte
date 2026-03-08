<script lang="ts">
  import { BookOpen } from '@lucide/svelte';
  import type { Snippet } from 'svelte';

  interface Props {
    href: string;
    name: string;
    previewBookIds: string[];
    bookCount: number;
    badgeLabel: string;
    badgeClass: string;
    icon?: Snippet;
    overlay?: Snippet;
  }

  let { href, name, previewBookIds, bookCount, badgeLabel, badgeClass, icon, overlay }: Props = $props();
</script>

<div class="bg-card card-soft rounded-2xl overflow-hidden group hover:shadow-lg transition-all duration-200 relative">
  {#if overlay}
    {@render overlay()}
  {/if}

  <a {href} class="flex flex-col">
    <!-- Hero cover area -->
    <div class="relative h-60 overflow-hidden bg-secondary">
      {#if previewBookIds.length > 0}
        <!-- Blurred background from first cover -->
        <img
          src="/covers/{previewBookIds[0]}.jpg"
          alt=""
          class="absolute inset-0 w-full h-full object-cover blur-xl scale-110 opacity-60"
        />
        <div class="absolute inset-0 bg-black/10"></div>

        <!-- Fanned book covers -->
        <div class="relative h-full flex items-center justify-center">
          {#each previewBookIds.slice(0, 4) as bookId, i}
            {@const count = Math.min(previewBookIds.length, 4)}
            {@const rotation = (i - (count - 1) / 2) * 6}
            {@const translateX = (i - (count - 1) / 2) * 60}
            <img
              src="/covers/{bookId}.jpg"
              alt=""
              class="h-40 w-auto object-cover rounded-xs absolute"
              style="transform: rotate({rotation}deg) translateX({translateX}px); z-index: {i}; box-shadow: -10px 20px 25px -5px rgba(0, 0, 0, 0.5), 0 10px 10px -5px rgba(0, 0, 0, 0.3); border-right: 2px solid rgba(255, 255, 255, 0.5)"
            />
          {/each}
        </div>
      {:else}
        <div class="h-full flex items-center justify-center">
          <BookOpen class="text-muted-foreground/20" size={48} />
        </div>
      {/if}
    </div>

    <!-- Info bar -->
    <div class="p-4 flex items-center justify-between">
      <div class="flex items-center gap-2 min-w-0">
        {#if icon}
          {@render icon()}
        {/if}
        <h2 class="font-semibold text-foreground group-hover:text-primary transition-colors truncate">{name}</h2>
      </div>
      <div class="flex items-center gap-2 shrink-0 ml-3">
        <span class="text-xs px-2.5 py-1 rounded-full font-medium {badgeClass}">
          {badgeLabel}
        </span>
        <span class="text-xs text-muted-foreground">
          {bookCount} {bookCount === 1 ? 'book' : 'books'}
        </span>
      </div>
    </div>
  </a>
</div>
