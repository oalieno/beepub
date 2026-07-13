<script lang="ts">
  import { page } from "$app/state";
  import { authStore } from "$lib/stores/auth";
  import { isLocalMode } from "$lib/api/client";
  import { sidebarCollapsed, toggleSidebar } from "$lib/stores/sidebar";
  import DesktopSidebar from "$lib/components/DesktopSidebar.svelte";
  import LocalTabBar from "$lib/components/LocalTabBar.svelte";
  import LocalTopBar from "$lib/components/LocalTopBar.svelte";
  import MobileTabBar from "$lib/components/MobileTabBar.svelte";
  import MobileTopBar from "$lib/components/MobileTopBar.svelte";
  import SearchModal from "$lib/components/SearchModal.svelte";
  import { searchModalOpen } from "$lib/stores/search";
  import type { Snippet } from "svelte";

  let { children }: { children: Snippet } = $props();

  // Serverless local mode gets its own chrome below. Entering/leaving the
  // mode always routes through (auth) pages, so this layout remounts and a
  // one-time read is enough.
  const localMode = isLocalMode();

  let isAuthenticated = $derived(!!$authStore.user || !!page.data.user);
  let isBookDetail = $derived(/^\/books\/[^/]+$/.test(page.url.pathname));
</script>

<svelte:window
  onkeydown={(e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "k") {
      e.preventDefault();
      searchModalOpen.update((v) => !v);
    }
    if ((e.metaKey || e.ctrlKey) && e.key === "b") {
      e.preventDefault();
      toggleSidebar();
    }
  }}
/>

<!-- localMode wins over isAuthenticated: entering serverless means no
     server session can exist, but page.data.user is cached load output
     and may lag until invalidation lands. -->
{#if localMode}
  <LocalTopBar />
  <LocalTabBar />

  <main
    class="pt-[calc(48px+env(safe-area-inset-top,0px))] pb-[calc(56px+env(safe-area-inset-bottom,0px))]"
  >
    {@render children()}
  </main>
{:else if isAuthenticated}
  <!-- Desktop: sidebar -->
  <DesktopSidebar onSearchOpen={() => searchModalOpen.set(true)} />

  <!-- Mobile: top bar + bottom tab bar -->
  {#if !isBookDetail}
    <MobileTopBar onSearchOpen={() => searchModalOpen.set(true)} />
    <MobileTabBar />
  {/if}

  <main
    class="app-main transition-[padding-left] duration-200 ease-in-out {$sidebarCollapsed
      ? 'md:pl-16'
      : 'md:pl-[280px]'} {isBookDetail
      ? 'book-detail-safe-area'
      : 'pt-[calc(48px+env(safe-area-inset-top,0px))] pb-[calc(56px+env(safe-area-inset-bottom,0px))]'} md:pt-0 md:pb-0"
  >
    {@render children()}
  </main>

  <SearchModal bind:open={$searchModalOpen} />
{:else}
  <main>
    {@render children()}
  </main>
{/if}

<style>
  @media (max-width: 767px) {
    .book-detail-safe-area {
      padding-top: env(safe-area-inset-top, 0px);
    }
  }
  @media (min-width: 768px) {
    .app-main {
      padding-top: env(safe-area-inset-top, 0px);
      padding-right: env(safe-area-inset-right, 0px);
    }
  }
</style>
