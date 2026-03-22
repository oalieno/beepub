<script lang="ts">
  import { page } from "$app/stores";
  import { BookX } from "@lucide/svelte";
</script>

<svelte:head>
  <title>{$page.status} - BeePub</title>
</svelte:head>

<div class="flex flex-col items-center justify-center min-h-[60vh] px-4 text-center">
  <BookX class="text-muted-foreground/40 mb-4" size={48} strokeWidth={1.5} />
  <h1 class="text-4xl font-bold text-foreground mb-2">{$page.status}</h1>
  <p class="text-muted-foreground text-lg mb-6">
    {$page.error?.message || "Page not found"}
  </p>
  <a
    href="/"
    class="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-primary-foreground font-medium hover:opacity-90 transition-opacity"
  >
    Back to Home
  </a>
</div>
