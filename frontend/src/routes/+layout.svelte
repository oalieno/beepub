<script lang="ts">
  import "../app.css";
  import { browser } from "$app/environment";
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import { authStore } from "$lib/stores/auth";
  import { isNative } from "$lib/platform";
  import { hasServerUrl } from "$lib/api/client";
  import Navbar from "$lib/components/Navbar.svelte";
  import Toast from "$lib/components/Toast.svelte";
  import type { Snippet } from "svelte";
  import type { UserOut } from "$lib/types";

  let {
    data,
    children,
  }: {
    data: { user: UserOut | null };
    children: Snippet;
  } = $props();

  $effect(() => {
    if (browser && data.user) {
      authStore.setUser(data.user);
    }
  });

  // Client-side route guards for SPA (Capacitor) mode
  $effect(() => {
    if (browser && isNative()) {
      const path = page.url.pathname;
      // Must configure server URL before anything else
      if (!hasServerUrl() && path !== "/setup") {
        goto("/setup");
        return;
      }
      // Must be logged in (except setup and login pages)
      if (
        hasServerUrl() &&
        !$authStore.user &&
        path !== "/login" &&
        path !== "/setup"
      ) {
        goto("/login");
      }
    }
  });

  let isReaderPage = $derived(page.url.pathname.endsWith("/read"));
  let isAuthenticated = $derived(!!data.user || !!$authStore.user);
</script>

{#if !isReaderPage && isAuthenticated}
  <Navbar />
{/if}

<main
  class="{isReaderPage
    ? ''
    : isAuthenticated
      ? 'pt-16'
      : ''} min-h-screen bg-background text-foreground"
>
  {@render children()}
</main>

<Toast />
