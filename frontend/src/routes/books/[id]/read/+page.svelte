<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores/auth';
  import EpubReader from '$lib/components/reader/EpubReader.svelte';
  import Toolbar from '$lib/components/reader/Toolbar.svelte';

  $: bookId = $page.params.id;

  let title = '';
  let fontFamily = 'serif';
  let fontSize = 16;
  let percentage = 0;
  let reader: EpubReader;
  let ready = false;

  onMount(() => {
    if (!$authStore.token) {
      goto('/login');
      return;
    }
    const savedFont = localStorage.getItem('reader-font');
    const savedSize = localStorage.getItem('reader-size');
    if (savedFont) fontFamily = savedFont;
    if (savedSize) fontSize = parseInt(savedSize);
    ready = true;
  });

  function handleFontToggle() {
    fontFamily = fontFamily === 'serif' ? 'sans-serif' : 'serif';
    localStorage.setItem('reader-font', fontFamily);
  }

  function handleFontIncrease() {
    if (fontSize < 32) {
      fontSize += 2;
      localStorage.setItem('reader-size', String(fontSize));
    }
  }

  function handleFontDecrease() {
    if (fontSize > 10) {
      fontSize -= 2;
      localStorage.setItem('reader-size', String(fontSize));
    }
  }
</script>

<svelte:head>
  <title>{title || 'Reading'} - BeePub</title>
</svelte:head>

<div class="flex flex-col h-screen bg-gray-950">
  <Toolbar
    {title}
    {fontFamily}
    {fontSize}
    {percentage}
    on:prev={() => reader?.prev()}
    on:next={() => reader?.next()}
    on:fontToggle={handleFontToggle}
    on:fontIncrease={handleFontIncrease}
    on:fontDecrease={handleFontDecrease}
  />

  <div class="flex-1 overflow-hidden">
    {#if ready && $authStore.token}
      <EpubReader
        bind:this={reader}
        {bookId}
        token={$authStore.token}
        {fontFamily}
        {fontSize}
        on:title={(e) => (title = e.detail)}
        on:progress={(e) => (percentage = e.detail.percentage)}
      />
    {/if}
  </div>
</div>
