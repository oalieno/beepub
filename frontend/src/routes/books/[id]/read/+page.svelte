<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { authStore } from '$lib/stores/auth';
  import EpubReader from '$lib/components/reader/EpubReader.svelte';
  import Toolbar from '$lib/components/reader/Toolbar.svelte';
  import HighlightSidebar from '$lib/components/reader/HighlightSidebar.svelte';
  import TocSidebar from '$lib/components/reader/TocSidebar.svelte';
  import { booksApi } from '$lib/api/books';
  import { toastStore } from '$lib/stores/toast';
  import type { HighlightOut } from '$lib/types';

  let bookId = $derived($page.params.id as string);

  let title = $state('');
  let fontFamily = $state('serif');
  let fontSize = $state(16);
  let darkMode = $state(false);
  let percentage = $state(0);
  let currentPage = $state(0);
  let totalPages = $state(0);
  let pageMapReady = $state(false);
  let calculatingPages = $state(false);
  let toc = $state<{ label: string; href: string; subitems?: any[] }[]>([]);
  let reader: EpubReader = $state(null as any);
  let ready = $state(false);
  let isRtl = $state(false);
  let highlights = $state<HighlightOut[]>([]);
  let showHighlightSidebar = $state(false);
  let showTocSidebar = $state(false);

  onMount(() => {
    if (!$authStore.token) {
      goto('/login');
      return;
    }
    const savedFont = localStorage.getItem('reader-font');
    const savedSize = localStorage.getItem('reader-size');
    const savedTheme = localStorage.getItem('reader-dark');
    if (savedFont) fontFamily = savedFont;
    if (savedSize) fontSize = parseInt(savedSize);
    if (savedTheme) darkMode = savedTheme === '1';
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

  function handleThemeToggle() {
    darkMode = !darkMode;
    localStorage.setItem('reader-dark', darkMode ? '1' : '0');
  }
</script>

<svelte:head>
  <title>{title || 'Reading'} - BeePub</title>
</svelte:head>

<div class="flex flex-col h-screen {darkMode ? 'bg-gray-900' : 'bg-background'}">
  <Toolbar
    {bookId}
    {title}
    {fontFamily}
    {fontSize}
    {percentage}
    {currentPage}
    {totalPages}
    {pageMapReady}
    {calculatingPages}
    {darkMode}
    {toc}
    {isRtl}
    highlightCount={highlights.length}
    onprev={() => reader?.prev()}
    onnext={() => reader?.next()}
    onfontToggle={handleFontToggle}
    onfontIncrease={handleFontIncrease}
    onfontDecrease={handleFontDecrease}
    onthemeToggle={handleThemeToggle}
    onchapter={(href) => reader?.displayChapter(href)}
    onhighlights={() => { showHighlightSidebar = !showHighlightSidebar; showTocSidebar = false; }}
    ontoc_toggle={() => { showTocSidebar = !showTocSidebar; showHighlightSidebar = false; }}
  />

  <div class="flex-1 overflow-hidden relative">
    {#if ready && $authStore.token}
      <EpubReader
        bind:this={reader}
        {bookId}
        token={$authStore.token}
        {fontFamily}
        {fontSize}
        {darkMode}
        ontitle={(t) => (title = t)}
        onprogress={(p) => { percentage = p.percentage; currentPage = p.currentPage; totalPages = p.totalPages; pageMapReady = p.pageMapReady; calculatingPages = p.calculatingPages; }}
        ontoc={(t) => (toc = t)}
        ondirection={(rtl) => (isRtl = rtl)}
        onhighlightschange={(h) => (highlights = h)}
      />
    {/if}

    <!-- Bottom page indicator -->
    {#if pageMapReady && totalPages > 0}
      <div class="absolute bottom-0 left-0 right-0 flex items-center justify-center py-2 pointer-events-none">
        <span class="text-xs px-3 py-1 rounded-full flex items-center gap-1.5 {darkMode ? 'bg-gray-800/80 text-gray-400' : 'bg-black/5 text-muted-foreground'}">
          {currentPage} / {totalPages}
          {#if calculatingPages}
            <span class="inline-block w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin opacity-50"></span>
          {/if}
        </span>
      </div>
    {:else if calculatingPages}
      <div class="absolute bottom-0 left-0 right-0 flex items-center justify-center py-2 pointer-events-none">
        <span class="text-xs px-3 py-1 rounded-full flex items-center gap-1.5 {darkMode ? 'bg-gray-800/80 text-gray-400' : 'bg-black/5 text-muted-foreground'}">
          <span class="inline-block w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin opacity-50"></span>
        </span>
      </div>
    {/if}

    {#if showTocSidebar}
      <TocSidebar
        {toc}
        {darkMode}
        onchapter={(href) => { reader?.displayChapter(href); showTocSidebar = false; }}
        onclose={() => (showTocSidebar = false)}
      />
    {/if}

    {#if showHighlightSidebar}
      <HighlightSidebar
        {highlights}
        {darkMode}
        onselect={(hl) => { reader?.displayCfi(hl.cfi_range); showHighlightSidebar = false; }}
        ondelete={async (hl) => {
          if (!$authStore.token) return;
          try {
            await booksApi.deleteHighlight(bookId, hl.id, $authStore.token);
            highlights = highlights.filter((h) => h.id !== hl.id);
            toastStore.success('Highlight removed');
          } catch (e) {
            toastStore.error((e as Error).message);
          }
        }}
        onclose={() => (showHighlightSidebar = false)}
      />
    {/if}
  </div>
</div>
