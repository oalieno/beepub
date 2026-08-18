<script lang="ts">
  import { page } from "$app/state";
  import { activeLibraryHref } from "$lib/stores/activeLibrary";
  import { keyboardVisible } from "$lib/stores/keyboard";
  import * as m from "$lib/paraglide/messages.js";
  import { Home, ShelvingUnit, BookCopy, Compass, User } from "@lucide/svelte";

  // No per-tab online gating: offline replaces this chrome with the
  // offline shell entirely, so every tab rendered here is usable.
  const tabs = $derived([
    {
      href: "/",
      label: m.nav_home(),
      icon: Home,
      match: (p: string) => p === "/",
    },
    {
      href: "/bookshelves",
      label: m.nav_shelves(),
      icon: ShelvingUnit,
      // /my-books is the system-shelf detail route — keep the tab lit there.
      match: (p: string) =>
        p.startsWith("/bookshelves") || p.startsWith("/my-books"),
    },
    {
      // Calibre-style: jump straight into the active library; the cards
      // page one level up (via its back button) is the switcher.
      href: $activeLibraryHref,
      label: m.nav_libraries(),
      icon: BookCopy,
      match: (p: string) =>
        p.startsWith("/libraries") || p.startsWith("/local"),
    },
    {
      href: "/discover",
      label: m.nav_discover(),
      icon: Compass,
      match: (p: string) => p.startsWith("/discover"),
    },
    {
      href: "/profile",
      label: m.nav_profile(),
      icon: User,
      match: (p: string) => p.startsWith("/profile"),
    },
  ]);
</script>

{#if !$keyboardVisible}
  <nav
    class="md:hidden fixed bottom-0 left-0 right-0 z-40 bg-background/95 backdrop-blur-sm border-t border-border"
    style="padding-bottom: env(safe-area-inset-bottom, 0px);"
    aria-label={m.nav_main_navigation()}
  >
    <div class="flex items-stretch">
      {#each tabs as tab}
        {@const active = tab.match(page.url.pathname)}
        <a
          href={tab.href}
          aria-current={active ? "page" : undefined}
          class="flex-1 flex flex-col items-center justify-center gap-0.5 py-2 min-h-[44px] transition-colors {active
            ? 'text-primary'
            : 'text-muted-foreground'}"
        >
          <tab.icon size={22} />
          <span class="text-[10px] font-medium">{tab.label}</span>
        </a>
      {/each}
    </div>
  </nav>
{/if}
