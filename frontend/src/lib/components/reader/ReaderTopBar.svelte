<script lang="ts">
  import { ArrowLeft } from "@lucide/svelte";
  import { goto } from "$app/navigation";

  let {
    bookId = "",
    title = "",
    percentage = 0,
    darkMode = false,
  }: {
    bookId?: string;
    title?: string;
    percentage?: number;
    darkMode?: boolean;
  } = $props();
</script>

<div
  class="md:hidden shrink-0 {darkMode
    ? 'bg-gray-900 border-b border-gray-800'
    : 'bg-background border-b border-border/50'}"
  style="padding-top: env(safe-area-inset-top, 0px);"
>
  <div class="flex items-center gap-3 px-3 h-11" role="banner">
    <button
      class="p-1.5 -ml-1 rounded-md transition-colors {darkMode
        ? 'text-gray-400 hover:bg-gray-800'
        : 'text-muted-foreground hover:bg-secondary'}"
      onclick={() => goto(`/books/${bookId}`, { replaceState: true })}
      aria-label="Back to book detail"
    >
      <ArrowLeft size={20} />
    </button>
    <div class="flex-1 min-w-0">
      <p
        class="text-sm font-medium truncate {darkMode
          ? 'text-gray-200'
          : 'text-foreground'}"
      >
        {title || "Loading..."}
      </p>
    </div>
    <span
      class="text-xs shrink-0 {darkMode
        ? 'text-gray-500'
        : 'text-muted-foreground'}"
    >
      {percentage}%
    </span>
  </div>
</div>
