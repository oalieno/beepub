<script lang="ts">
  import { page } from "$app/state";
</script>

<svelte:head>
  <title>{page.status} - BeePub</title>
</svelte:head>

<div
  class="flex flex-col items-center justify-center min-h-[60dvh] px-4 py-12 text-center"
>
  <img
    src="/404.png"
    alt="404"
    style="max-width: min(24rem, 70vw);"
    class="mb-4 sm:!max-w-96"
  />
  <p class="text-muted-foreground text-lg mb-6">
    {page.error?.message || "Page not found"}
  </p>
  <a
    href="/"
    class="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-primary-foreground font-medium hover:opacity-90 transition-opacity"
  >
    Back to Home
  </a>
</div>
