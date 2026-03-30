<script lang="ts">
  import "../app.css";
  import { browser } from "$app/environment";
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import { authStore } from "$lib/stores/auth";
  import { isNative } from "$lib/platform";
  import { hasServerUrl } from "$lib/api/client";
  import { initNetworkWatcher } from "$lib/services/network";
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

  onMount(() => {
    initNetworkWatcher();
  });

  $effect(() => {
    if (browser && data.user) {
      authStore.setUser(data.user);
    }
  });

  // Clean up stale localStorage token in web mode (only native uses Bearer auth)
  $effect(() => {
    if (browser && !isNative() && localStorage.getItem("token")) {
      localStorage.removeItem("token");
    }
  });

  // Client-side route guards for SPA (Capacitor) mode
  let nativeReady = $state(!isNative());
  $effect(() => {
    if (browser && isNative() && page.url) {
      const path = page.url.pathname;
      if (!hasServerUrl() && path !== "/setup") {
        goto("/setup");
        return;
      }
      if (
        hasServerUrl() &&
        !$authStore.user &&
        path !== "/login" &&
        path !== "/setup"
      ) {
        goto("/login");
        return;
      }
      nativeReady = true;
    }
  });
</script>

{#if nativeReady}
  <div class="min-h-screen bg-background text-foreground">
    {@render children()}
  </div>
  <Toast />
{/if}
