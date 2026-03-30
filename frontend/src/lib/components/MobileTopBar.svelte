<script lang="ts">
  import { page } from "$app/state";
  import { isOnline } from "$lib/services/network";
  import { toastStore } from "$lib/stores/toast";
  import { Search, Dices } from "@lucide/svelte";

  let { onSearchOpen }: { onSearchOpen: () => void } = $props();

  let online = $derived($isOnline);

  // Derive page title from route
  const titleMap: Record<string, string> = {
    "/": "Home",
    "/my-books": "My Books",
    "/libraries": "Libraries",
    "/bookshelves": "Shelves",
    "/highlights": "Highlights",
    "/discover": "Discover",
    "/gacha": "Gacha",
    "/downloads": "Downloads",
    "/admin": "Admin",
    "/profile": "Profile",
  };

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
        class="p-2 rounded-lg transition-colors {!online
          ? 'opacity-25 cursor-default'
          : 'text-muted-foreground hover:text-foreground hover:bg-secondary'}"
        onclick={() => {
          if (!online) {
            toastStore.info("Available when online");
            return;
          }
          onSearchOpen();
        }}
        aria-label="Search"
        aria-disabled={!online || undefined}
      >
        <Search size={20} />
      </button>
      <a
        href={!online ? undefined : "/gacha"}
        class="p-2 rounded-lg transition-colors {!online
          ? 'opacity-25 cursor-default'
          : page.url.pathname === '/gacha'
            ? 'bg-primary/10 text-primary'
            : 'text-muted-foreground hover:text-foreground hover:bg-secondary'}"
        aria-label="Gacha"
        aria-disabled={!online || undefined}
        onclick={!online
          ? (e: Event) => {
              e.preventDefault();
              toastStore.info("Available when online");
            }
          : undefined}
      >
        <Dices size={20} />
      </a>
    </div>
  </div>
</header>
