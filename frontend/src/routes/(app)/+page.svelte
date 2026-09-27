<script lang="ts">
  import { isLocalMode } from "$lib/api/client";
  import LocalHome from "$lib/components/home/LocalHome.svelte";
  import ServerHome from "$lib/components/home/ServerHome.svelte";
  import * as m from "$lib/paraglide/messages.js";

  // Home is the landing page in both modes; only where its books come
  // from differs. Mode switches are a full page load.
  const localMode = isLocalMode();
</script>

<svelte:head>
  <title>{m.home_page_title()}</title>
</svelte:head>

{#if localMode}
  <LocalHome />
{:else}
  <ServerHome />
{/if}
