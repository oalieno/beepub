<script lang="ts">
  import { page } from "$app/state";
  import * as m from "$lib/paraglide/messages.js";

  // Deeper paths first — matching is prefix-based.
  const titleMap = $derived<Record<string, string>>({
    "/local/highlights": m.nav_highlights(),
    "/local/settings": m.local_nav_settings(),
    "/local": m.local_nav_books(),
    "/catalogs": m.nav_catalogs(),
  });

  let pageTitle = $derived(() => {
    const path = page.url.pathname;
    for (const [prefix, title] of Object.entries(titleMap)) {
      if (path === prefix || path.startsWith(prefix)) {
        return title;
      }
    }
    return "BeePub";
  });
</script>

<header
  class="fixed top-0 left-0 right-0 z-40 bg-background/95 backdrop-blur-sm border-b border-border/50"
  style="padding-top: env(safe-area-inset-top, 0px); height: calc(48px + env(safe-area-inset-top, 0px));"
>
  <div class="h-[48px] px-4 flex items-center">
    <h1
      class="text-lg font-bold tracking-tight"
      style="font-family: var(--font-heading)"
    >
      {pageTitle()}
    </h1>
  </div>
</header>
