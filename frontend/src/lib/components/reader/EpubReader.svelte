<script lang="ts">
  import { onMount, onDestroy, createEventDispatcher } from 'svelte';
  import { booksApi } from '$lib/api/books';
  import { toastStore } from '$lib/stores/toast';
  import HighlightMenu from './HighlightMenu.svelte';
  import type { HighlightOut } from '$lib/types';

  export let bookId: string;
  export let token: string;

  const dispatch = createEventDispatcher<{
    progress: { cfi: string; percentage: number };
    title: string;
  }>();

  let container: HTMLDivElement;
  let book: ReturnType<typeof import('epubjs')['default']> | null = null;
  let rendition: ReturnType<typeof book.renderTo> | null = null;
  let highlights: HighlightOut[] = [];

  // Reader settings
  export let fontFamily = 'serif';
  export let fontSize = 16;

  // Highlight menu
  let showHighlightMenu = false;
  let highlightMenuX = 0;
  let highlightMenuY = 0;
  let selectedCfi = '';
  let selectedText = '';
  let existingHighlight: HighlightOut | null = null;

  let progressTimer: ReturnType<typeof setInterval> | null = null;
  let currentCfi = '';
  let currentPercentage = 0;

  const HIGHLIGHT_COLORS: Record<string, string> = {
    yellow: '#fef08a',
    green: '#bbf7d0',
    blue: '#bfdbfe',
    pink: '#fbcfe8',
    orange: '#fed7aa',
  };

  onMount(async () => {
    const Epub = (await import('epubjs')).default;

    // Set token cookie so the browser can authenticate resource requests (images, fonts)
    document.cookie = `token=${token}; path=/; SameSite=Lax`;

    // Use content endpoint as directory — epubjs will fetch individual files from the EPUB
    book = Epub(`/api/books/${bookId}/content/`, {
      openAs: 'directory',
    });

    rendition = book.renderTo(container, {
      width: '100%',
      height: '100%',
      spread: 'none',
    });

    // Apply theme
    applyTheme();

    // Load highlights
    try {
      highlights = await booksApi.getHighlights(bookId, token);
    } catch {
      // ignore
    }

    // Load progress
    try {
      const progress = await booksApi.getProgress(bookId, token);
      if (progress?.cfi) {
        await rendition.display(progress.cfi);
      } else {
        await rendition.display();
      }
    } catch {
      await rendition.display();
    }

    // Apply existing highlights
    applyAllHighlights();

    // Get book title
    book.loaded.metadata.then((meta: { title?: string }) => {
      if (meta.title) dispatch('title', meta.title);
    });

    // Track location changes
    rendition.on('locationChanged', (loc: { start: { cfi: string; percentage?: number } }) => {
      currentCfi = loc.start.cfi;
      currentPercentage = Math.round((loc.start.percentage ?? 0) * 100);
      dispatch('progress', { cfi: currentCfi, percentage: currentPercentage });
    });

    // Text selection for highlights
    rendition.on('selected', (cfiRange: string, contents: { window: Window }) => {
      const selection = contents.window.getSelection();
      if (!selection || selection.toString().trim() === '') return;
      selectedText = selection.toString().trim();
      selectedCfi = cfiRange;
      existingHighlight = highlights.find((h) => h.cfi_range === cfiRange) ?? null;

      // Position menu
      const range = selection.getRangeAt(0);
      const rect = range.getBoundingClientRect();
      const containerRect = container.getBoundingClientRect();
      highlightMenuX = rect.left - containerRect.left + rect.width / 2;
      highlightMenuY = rect.top - containerRect.top - 8;
      showHighlightMenu = true;
    });

    rendition.on('click', () => {
      showHighlightMenu = false;
    });

    // Save progress every 30s
    progressTimer = setInterval(saveProgress, 30000);
  });

  onDestroy(() => {
    if (progressTimer) clearInterval(progressTimer);
    saveProgress();
    rendition?.destroy();
    book?.destroy();
  });

  async function saveProgress() {
    if (!currentCfi) return;
    try {
      await booksApi.updateProgress(bookId, currentCfi, currentPercentage, token);
    } catch {
      // silent
    }
  }

  function applyTheme() {
    if (!rendition) return;
    rendition.themes.default({
      body: {
        'font-family': fontFamily === 'serif' ? 'Georgia, serif' : 'system-ui, sans-serif',
        'font-size': `${fontSize}px`,
        'line-height': '1.8',
        color: '#e5e7eb',
        background: '#111827',
        padding: '2rem !important',
      },
      '::selection': {
        background: 'rgba(245, 158, 11, 0.4)',
      },
    });
    rendition.themes.select('default');
  }

  function applyAllHighlights() {
    if (!rendition) return;
    for (const h of highlights) {
      const color = HIGHLIGHT_COLORS[h.color] ?? HIGHLIGHT_COLORS.yellow;
      rendition.annotations.highlight(h.cfi_range, {}, () => {}, 'hl', {
        fill: color,
        'fill-opacity': '0.5',
      });
    }
  }

  export function prev() {
    rendition?.prev();
  }

  export function next() {
    rendition?.next();
  }

  $: if (rendition) {
    applyTheme();
  }

  async function onHighlightColor(event: CustomEvent<{ color: string }>) {
    const color = event.detail.color;
    showHighlightMenu = false;
    if (!selectedCfi || !selectedText) return;

    const colorKey = Object.entries(HIGHLIGHT_COLORS).find(([, v]) => v === color)?.[0] ?? color;

    try {
      if (existingHighlight) {
        const updated = await booksApi.updateHighlight(bookId, existingHighlight.id, { color: colorKey }, token);
        highlights = highlights.map((h) => (h.id === updated.id ? updated : h));
        rendition?.annotations.remove(selectedCfi, 'highlight');
      } else {
        const created = await booksApi.createHighlight(bookId, { cfi_range: selectedCfi, text: selectedText, color: colorKey }, token);
        highlights = [...highlights, created];
      }

      const fill = HIGHLIGHT_COLORS[colorKey] ?? HIGHLIGHT_COLORS.yellow;
      rendition?.annotations.highlight(selectedCfi, {}, () => {}, 'hl', {
        fill,
        'fill-opacity': '0.5',
      });
      toastStore.success('Highlight saved');
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  async function onRemoveHighlight() {
    showHighlightMenu = false;
    if (!existingHighlight) return;
    try {
      await booksApi.deleteHighlight(bookId, existingHighlight.id, token);
      highlights = highlights.filter((h) => h.id !== existingHighlight!.id);
      rendition?.annotations.remove(selectedCfi, 'highlight');
      toastStore.success('Highlight removed');
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }
</script>

<div class="relative w-full h-full">
  <div bind:this={container} class="w-full h-full"></div>

  {#if showHighlightMenu}
    <div
      class="absolute z-20 transform -translate-x-1/2 -translate-y-full"
      style="left: {highlightMenuX}px; top: {highlightMenuY}px;"
    >
      <HighlightMenu
        hasExisting={!!existingHighlight}
        on:color={onHighlightColor}
        on:remove={onRemoveHighlight}
        on:close={() => (showHighlightMenu = false)}
      />
    </div>
  {/if}
</div>
