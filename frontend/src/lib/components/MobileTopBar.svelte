<script lang="ts">
  import { page } from "$app/state";
  import * as m from "$lib/paraglide/messages.js";
  import { ArrowLeftRight, Search, Dices } from "@lucide/svelte";
  import { isLocalMode } from "$lib/api/client";
  import { navTitle } from "$lib/nav";
  import { isNative } from "$lib/platform";

  let { onSearchOpen }: { onSearchOpen?: () => void } = $props();

  // Mode switches are a full page load, so a one-time read is enough.
  const mode = isLocalMode() ? "local" : "server";

  let pageTitle = $derived(navTitle(mode, page.url.pathname));
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
      {pageTitle}
    </h1>

    <div class="flex items-center gap-1">
      {#if isNative()}
        <a
          href="/mode"
          class="p-2 rounded-lg transition-colors text-muted-foreground hover:text-foreground hover:bg-secondary"
          aria-label={m.mode_switch_title()}
        >
          <ArrowLeftRight size={20} />
        </a>
      {/if}
      <!-- Search and gacha query the server: server mode only. -->
      {#if mode === "server"}
        <button
          class="p-2 rounded-lg transition-colors text-muted-foreground hover:text-foreground hover:bg-secondary"
          onclick={onSearchOpen}
          aria-label={m.nav_search()}
        >
          <Search size={20} />
        </button>
        <a
          href="/gacha"
          class="p-2 rounded-lg transition-colors {page.url.pathname ===
          '/gacha'
            ? 'bg-primary/10 text-primary'
            : 'text-muted-foreground hover:text-foreground hover:bg-secondary'}"
          aria-label={m.nav_gacha()}
        >
          <Dices size={20} />
        </a>
      {/if}
    </div>
  </div>
</header>
