<script lang="ts">
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import { authStore } from "$lib/stores/auth";
  import { isLocalMode } from "$lib/api/client";
  import { offlineShell } from "$lib/services/offlineShell";
  import { sidebarCollapsed, toggleSidebar } from "$lib/stores/sidebar";
  import DesktopSidebar from "$lib/components/DesktopSidebar.svelte";
  import LocalTabBar from "$lib/components/LocalTabBar.svelte";
  import LocalTopBar from "$lib/components/LocalTopBar.svelte";
  import MobileTabBar from "$lib/components/MobileTabBar.svelte";
  import MobileTopBar from "$lib/components/MobileTopBar.svelte";
  import OfflineBanner from "$lib/components/OfflineBanner.svelte";
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

  // Offline shell route guard: the shell is an allowlist — the device
  // shelf is the only surface that exists offline, everything else
  // redirects there. The reader lives in its own layout group and is
  // deliberately outside this guard (going offline mid-book must never
  // interrupt reading).
  $effect(() => {
    if (!localMode && $offlineShell && page.url.pathname !== "/local") {
      void goto("/local", { replaceState: true });
    }
  });
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
{:else if isAuthenticated && $offlineShell}
  <!-- Offline shell: the app collapses to the device shelf behind a
       minimal chrome. No tab bar, no sidebar — there is exactly one
       surface, so the only affordances are the banner's retry and the
       books themselves. -->
  <LocalTopBar />

  <main
    class="pt-[calc(48px+env(safe-area-inset-top,0px))] pb-[env(safe-area-inset-bottom,0px)]"
  >
    <div class="px-6 sm:px-8 pt-6">
      <OfflineBanner />
    </div>
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
