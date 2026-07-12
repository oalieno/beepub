<script lang="ts">
  import { page } from "$app/state";
  import * as m from "$lib/paraglide/messages.js";
  import { BookOpen, Highlighter, Settings } from "@lucide/svelte";
  import { onMount, onDestroy } from "svelte";

  // Serverless local mode has no desktop sidebar — the tab bar is the only
  // navigation, so unlike MobileTabBar it stays visible at every width.
  const tabs = $derived([
    {
      href: "/local",
      label: m.local_nav_books(),
      icon: BookOpen,
      match: (p: string) => p === "/local" || p.startsWith("/catalogs"),
    },
    {
      href: "/local/highlights",
      label: m.nav_highlights(),
      icon: Highlighter,
      match: (p: string) => p.startsWith("/local/highlights"),
    },
    {
      href: "/local/settings",
      label: m.local_nav_settings(),
      icon: Settings,
      match: (p: string) => p.startsWith("/local/settings"),
    },
  ]);

  // Hide tab bar when iOS keyboard is visible
  let keyboardVisible = $state(false);
  let viewport: VisualViewport | null = null;

  function onViewportResize() {
    if (!viewport) return;
    // When keyboard opens, visualViewport.height shrinks significantly
    keyboardVisible = viewport.height < window.innerHeight * 0.75;
  }

  onMount(() => {
    viewport = window.visualViewport ?? null;
    if (viewport) {
      viewport.addEventListener("resize", onViewportResize);
    }
  });

  onDestroy(() => {
    if (viewport) {
      viewport.removeEventListener("resize", onViewportResize);
    }
  });
</script>

{#if !keyboardVisible}
  <nav
    class="fixed bottom-0 left-0 right-0 z-40 bg-background/95 backdrop-blur-sm border-t border-border"
    style="padding-bottom: env(safe-area-inset-bottom, 0px);"
    aria-label={m.nav_main_navigation()}
  >
    <div class="flex items-stretch max-w-lg mx-auto">
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
