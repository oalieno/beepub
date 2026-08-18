<script lang="ts">
  import { page } from "$app/state";
  import * as m from "$lib/paraglide/messages.js";
  import { Search, Dices } from "@lucide/svelte";

  let { onSearchOpen }: { onSearchOpen: () => void } = $props();

  // Derive page title from route
  const titleMap = $derived<Record<string, string>>({
    "/": m.nav_home(),
    "/my-books": m.nav_shelves(),
    "/libraries": m.nav_libraries(),
    "/bookshelves": m.nav_shelves(),
    "/highlights": m.nav_highlights(),
    "/discover": m.nav_discover(),
    "/gacha": m.nav_gacha(),
    "/admin": m.nav_admin(),
    "/profile": m.nav_profile(),
    "/local": m.nav_local_books(),
    "/catalogs": m.nav_catalogs(),
  });

  let pageTitle = $derived(() => {
    const path = page.url.pathname;
    for (const [prefix, title] of Object.entries(titleMap)) {
      if (path === prefix || (prefix !== "/" && path.startsWith(prefix))) {
        return title;
      }
    }
    return "BeePub";
  });
</script>

<header
  class="md:hidden fixed top-0 left-0 right-0 z-40 bg-background/95 backdrop-blur-sm border-b border-border/50"
  style="padding-top: env(safe-area-inset-top, 0px); height: calc(48px + env(safe-area-inset-top, 0px));"
>
  <div class="h-[48px] px-4 flex items-center justify-between">
    <h1
      class="text-lg font-bold tracking-tight"
      style="font-family: var(--font-heading)"
    >
      {pageTitle()}
    </h1>

    <div class="flex items-center gap-1">
      <button
        class="p-2 rounded-lg transition-colors text-muted-foreground hover:text-foreground hover:bg-secondary"
        onclick={onSearchOpen}
        aria-label={m.nav_search()}
      >
        <Search size={20} />
      </button>
      <a
        href="/gacha"
        class="p-2 rounded-lg transition-colors {page.url.pathname === '/gacha'
          ? 'bg-primary/10 text-primary'
          : 'text-muted-foreground hover:text-foreground hover:bg-secondary'}"
        aria-label={m.nav_gacha()}
      >
        <Dices size={20} />
      </a>
    </div>
  </div>
</header>
