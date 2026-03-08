<script lang="ts">
  import "../app.css";
  import { browser } from "$app/environment";
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

  $effect(() => {
    if (browser) {
      if (data.user && data.token) {
        authStore.login(data.user, data.token);
      } else {
        authStore.init();
      }
    }
  });

  let isReaderPage = $derived($page.url.pathname.endsWith("/read"));
</script>

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

<Toast />
