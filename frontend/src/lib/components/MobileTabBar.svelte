<script lang="ts">
  import { page } from "$app/state";
  import { isLocalMode } from "$lib/api/client";
  import { navTabs } from "$lib/nav";
  import { isNative } from "$lib/platform";
  import { activeLibraryHref } from "$lib/stores/activeLibrary";
  import { keyboardVisible } from "$lib/stores/keyboard";
  import * as m from "$lib/paraglide/messages.js";

  // Mode switches are a full page load, so a one-time read is enough.
  const mode = isLocalMode() ? "local" : "server";

  // No per-tab online gating: offline replaces this chrome with the
  // disconnect screen entirely, so every tab rendered here is usable.
  const tabs = $derived(
    navTabs({
      mode,
      libraryHref: $activeLibraryHref,
      native: isNative(),
      admin: false,
    }),
  );
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
