<script lang="ts">
  import { onMount } from "svelte";
  import GachaBookPull from "$lib/components/GachaBookPull.svelte";

  onMount(() => {
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  });
</script>

<svelte:head>
  <title>BeePub - 抽書</title>
</svelte:head>

<div class="max-w-6xl mx-auto px-4 sm:px-6 overflow-hidden">
  <GachaBookPull />
</div>
