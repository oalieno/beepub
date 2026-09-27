<script lang="ts">
  import { page } from "$app/state";
  import * as m from "$lib/paraglide/messages.js";
</script>

<svelte:head>
  <title>{page.status} - BeePub</title>
</svelte:head>

<!-- The root layout adds no chrome, so true centering = the full
     viewport; a fixed-height image box would letterbox and drag the
     visual weight upward, so the image keeps its own ratio instead. -->
<div
  class="flex min-h-dvh flex-col items-center justify-center px-4 py-8 text-center"
>
  <img
    src={page.status >= 500 ? "/error-500.png" : "/error-404.png"}
    alt={page.status >= 500
      ? "BeePub mascot slumped against a cracked 500, smoke rising from its antennae"
      : "BeePub mascot peeking out of a hole it dug in front of a cracked 404, puzzled"}
    style="width: min(34rem, 85vw); max-height: 42dvh; height: auto; object-fit: contain;"
    class="mb-4"
  />
  <p class="text-muted-foreground text-lg mb-6">
    {page.status >= 500 ? m.error_server() : m.error_not_found()}
  </p>
  <a
    href="/"
    class="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-primary-foreground font-medium hover:opacity-90 transition-opacity"
  >
    {m.error_back_home()}
  </a>
</div>
