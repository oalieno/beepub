<script lang="ts">
  import { onMount } from "svelte";
  import GachaBookPull from "$lib/components/GachaBookPull.svelte";
  import * as m from "$lib/paraglide/messages.js";

  onMount(() => {
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  });
</script>

<svelte:head>
  <title>{m.gacha_page_title()}</title>
</svelte:head>

<div class="max-w-6xl mx-auto px-4 sm:px-6 overflow-hidden">
  <GachaBookPull />
</div>
