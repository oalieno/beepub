<script lang="ts">
  import "../app.css";
  import { browser } from "$app/environment";
  import { page } from "$app/state";
  import { authStore } from "$lib/stores/auth";
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
      authStore.login(data.user);
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
