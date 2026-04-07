<script lang="ts">
  import { page } from "$app/state";
  import { authStore } from "$lib/stores/auth";
  import DesktopSidebar from "$lib/components/DesktopSidebar.svelte";
  import MobileTabBar from "$lib/components/MobileTabBar.svelte";
  import MobileTopBar from "$lib/components/MobileTopBar.svelte";
  import SearchModal from "$lib/components/SearchModal.svelte";
  import type { Snippet } from "svelte";

  let { children }: { children: Snippet } = $props();

  let searchOpen = $state(false);
  let isAuthenticated = $derived(!!$authStore.user || !!page.data.user);
  let isBookDetail = $derived(/^\/books\/[^/]+$/.test(page.url.pathname));
</script>

<svelte:window
  onkeydown={(e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "k") {
      e.preventDefault();
      searchOpen = !searchOpen;
    }
  }}
/>

{#if isAuthenticated}
  <!-- Desktop: sidebar -->
  <DesktopSidebar onSearchOpen={() => (searchOpen = true)} />

  <!-- Mobile: top bar + bottom tab bar -->
  {#if !isBookDetail}
    <MobileTopBar onSearchOpen={() => (searchOpen = true)} />
    <MobileTabBar />
  {/if}

  <main
    class="md:pl-[280px] {isBookDetail
      ? 'book-detail-safe-area'
      : 'pt-[calc(48px+env(safe-area-inset-top,0px))] pb-[calc(56px+env(safe-area-inset-bottom,0px))]'} md:pt-0 md:pb-0"
  >
    {@render children()}
  </main>

  <SearchModal bind:open={searchOpen} />
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
</style>
