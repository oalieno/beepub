<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { ArrowLeft, ChevronLeft, ChevronRight, Minus, Plus, Type } from 'lucide-svelte';

  export let title = '';
  export let fontFamily = 'serif';
  export let fontSize = 16;
  export let percentage = 0;

  const dispatch = createEventDispatcher<{
    prev: void;
    next: void;
    fontToggle: void;
    fontIncrease: void;
    fontDecrease: void;
  }>();
</script>

<div class="h-14 bg-gray-900 border-b border-gray-800 flex items-center px-4 gap-3 z-10">
  <a
    href={typeof window !== 'undefined' ? (document.referrer || '/') : '/'}
    class="text-gray-400 hover:text-white transition-colors"
    aria-label="Go back"
  >
    <ArrowLeft size={20} />
  </a>

  <div class="flex-1 min-w-0">
    <p class="text-sm font-medium truncate">{title}</p>
    <p class="text-xs text-gray-500">{percentage}%</p>
  </div>

  <div class="flex items-center gap-1">
    <!-- Font family toggle -->
    <button
      class="p-2 text-gray-400 hover:text-white transition-colors rounded"
      title="Toggle font family"
      on:click={() => dispatch('fontToggle')}
    >
      <Type size={16} />
      <span class="text-xs ml-1">{fontFamily === 'serif' ? 'Serif' : 'Sans'}</span>
    </button>

    <!-- Font size -->
    <button
      class="p-1.5 text-gray-400 hover:text-white transition-colors rounded"
      on:click={() => dispatch('fontDecrease')}
      disabled={fontSize <= 10}
    >
      <Minus size={14} />
    </button>
    <span class="text-xs w-8 text-center text-gray-400">{fontSize}px</span>
    <button
      class="p-1.5 text-gray-400 hover:text-white transition-colors rounded"
      on:click={() => dispatch('fontIncrease')}
      disabled={fontSize >= 32}
    >
      <Plus size={14} />
    </button>
  </div>

  <!-- Nav -->
  <div class="flex items-center gap-1">
    <button
      class="p-2 text-gray-400 hover:text-white transition-colors rounded"
      on:click={() => dispatch('prev')}
    >
      <ChevronLeft size={20} />
    </button>
    <button
      class="p-2 text-gray-400 hover:text-white transition-colors rounded"
      on:click={() => dispatch('next')}
    >
      <ChevronRight size={20} />
    </button>
  </div>
</div>
