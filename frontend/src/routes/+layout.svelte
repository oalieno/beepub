<script lang="ts">
  import "../app.css";
  import { browser } from "$app/environment";
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import { authStore } from "$lib/stores/auth";
  import { isNative } from "$lib/platform";
  import { hasServerUrl, isLocalMode } from "$lib/api/client";
  import { initNetworkWatcher } from "$lib/services/network";
  import { initReadingSync, linkAndSyncAll } from "$lib/services/readingSync";
  import Toast from "$lib/components/Toast.svelte";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
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
    initReadingSync();
  });

  $effect(() => {
    if (browser && data.user) {
      authStore.setUser(data.user);
    }
  });

  // Local-book sync fires when a user appears — cold start rehydrate and
  // fresh login both land here (login routes through authStore too).
  let prevUser: unknown = null;
  $effect(() => {
    const user = $authStore.user;
    if (
      browser &&
      user &&
      !prevUser &&
      isNative() &&
      !isLocalMode() &&
      hasServerUrl()
    ) {
      void linkAndSyncAll({ force: true });
    }
    prevUser = user;
  });

  // Clean up stale localStorage token in web mode (only native uses Bearer auth)
  $effect(() => {
    if (browser && !isNative() && localStorage.getItem("token")) {
      localStorage.removeItem("token");
    }
  });

  // Local mode only works on pages that don't need a server: the shelf,
  // OPDS catalogs, setup (to connect later), the mode switcher, and the
  // reader for local books.
  function isLocalPath(path: string): boolean {
    return (
      path.startsWith("/local") ||
      path.startsWith("/catalogs") ||
      path === "/setup" ||
      path === "/mode" ||
      /^\/books\/[^/]+\/read/.test(path)
    );
  }

  // Client-side route guards for SPA (Capacitor) mode
  let nativeReady = $state(!isNative());
  $effect(() => {
    if (browser && isNative() && page.url) {
      const path = page.url.pathname;
      if (isLocalMode()) {
        if (!isLocalPath(path)) {
          goto("/local");
          return;
        }
      } else if (!hasServerUrl()) {
        if (path !== "/setup") {
          goto("/setup");
          return;
        }
      } else if (!$authStore.user && path !== "/login" && path !== "/setup") {
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
  <ConfirmDialog />
{/if}
