<script lang="ts">
  import '../app.css';
  import { browser } from '$app/environment';
  import { page } from '$app/stores';
  import { authStore } from '$lib/stores/auth';
  import { toastStore } from '$lib/stores/toast';
  import Navbar from '$lib/components/Navbar.svelte';
  import Toast from '$lib/components/Toast.svelte';

  export let data: { user: import('$lib/types').UserOut | null; token: string | null };

  // Reactive: runs before child onMount, re-runs on navigation
  $: if (browser) {
    if (data.user && data.token) {
      authStore.login(data.user, data.token);
    } else {
      authStore.init();
    }
  }

  $: isReaderPage = $page.url.pathname.endsWith('/read');
</script>

{#if !isReaderPage && $authStore.user}
  <Navbar />
{/if}

<main class="{isReaderPage ? '' : $authStore.user ? 'pt-16' : ''} min-h-screen bg-gray-900 text-white">
  <slot />
</main>

<Toast />
