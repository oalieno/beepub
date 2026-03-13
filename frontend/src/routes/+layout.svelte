<script lang="ts">
  import "../app.css";
  import { browser } from "$app/environment";
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";
  import { authStore } from "$lib/stores/auth";
  import Navbar from "$lib/components/Navbar.svelte";
  import Toast from "$lib/components/Toast.svelte";
  import type { Snippet } from "svelte";
  import type { UserOut } from "$lib/types";

  let {
    data,
    children,
  }: {
    data: { user: UserOut | null; token: string | null };
    children: Snippet;
  } = $props();

  let authRecovering = $state(false);

  $effect(() => {
    if (browser) {
      if (data.user && data.token) {
        // SSR validated successfully
        authStore.login(data.user, data.token);
        authRecovering = false;
      } else if (data.token && !data.user) {
        // SSR had token but couldn't validate user (e.g. network error on iOS PWA resume)
        authRecovering = true;
        authStore.init();
        fetch("/api/auth/me", {
          headers: { Authorization: `Bearer ${data.token}` },
        })
          .then(async (res) => {
            if (res.ok) {
              const user = await res.json();
              authStore.login(user, data.token!);
            } else if (res.status === 401 || res.status === 403) {
              authStore.logout();
              goto("/login");
            }
          })
          .catch(() => {
            // Network still down — keep localStorage state
          })
          .finally(() => {
            authRecovering = false;
          });
      } else {
        authStore.init();
      }
    }
  });

  let isReaderPage = $derived($page.url.pathname.endsWith("/read"));
</script>

{#if authRecovering}
  <div class="min-h-screen flex items-center justify-center bg-background">
    <div class="animate-pulse text-muted-foreground text-lg">Loading…</div>
  </div>
{:else}
  {#if !isReaderPage && $authStore.user}
    <Navbar />
  {/if}

  <main
    class="{isReaderPage
      ? ''
      : $authStore.user
        ? 'pt-16'
        : ''} min-h-screen bg-background text-foreground"
  >
    {@render children()}
  </main>
{/if}

<Toast />
