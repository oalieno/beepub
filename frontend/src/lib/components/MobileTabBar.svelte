<script lang="ts">
  import { page } from "$app/state";
  import { isOnline } from "$lib/services/network";
  import { toastStore } from "$lib/stores/toast";
  import { Home, Library, Search, User } from "@lucide/svelte";
  import { onMount, onDestroy } from "svelte";

  let online = $derived($isOnline);

  const tabs = [
    {
      href: "/",
      label: "Home",
      icon: Home,
      match: (p: string) => p === "/",
      requiresOnline: false,
    },
    {
      href: "/libraries",
      label: "Library",
      icon: Library,
      match: (p: string) => p.startsWith("/libraries"),
      requiresOnline: true,
    },
    {
      href: "/discover",
      label: "Discover",
      icon: Search,
      match: (p: string) => p.startsWith("/discover"),
      requiresOnline: true,
    },
    {
      href: "/profile",
      label: "Profile",
      icon: User,
      match: (p: string) => p.startsWith("/profile"),
      requiresOnline: false,
    },
  ];

  function handleDisabledClick(e: Event) {
    e.preventDefault();
    toastStore.info("Available when online");
  }

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
    class="md:hidden fixed bottom-0 left-0 right-0 z-40 bg-background/95 backdrop-blur-sm border-t border-border"
    style="padding-bottom: env(safe-area-inset-bottom, 0px);"
    aria-label="Main navigation"
  >
    <div class="flex items-stretch" role="tablist">
      {#each tabs as tab}
        {@const active = tab.match(page.url.pathname)}
        {@const disabled = !online && tab.requiresOnline}
        <a
          href={disabled ? undefined : tab.href}
          role="tab"
          aria-selected={active}
          aria-current={active ? "page" : undefined}
          aria-disabled={disabled || undefined}
          class="flex-1 flex flex-col items-center justify-center gap-0.5 py-2 min-h-[44px] transition-colors {disabled
            ? 'opacity-25 cursor-default'
            : active
              ? 'text-primary'
              : 'text-muted-foreground'}"
          onclick={disabled ? handleDisabledClick : undefined}
        >
          <tab.icon size={22} />
          <span class="text-[10px] font-medium">{tab.label}</span>
        </a>
      {/each}
    </div>
  </nav>
{/if}
