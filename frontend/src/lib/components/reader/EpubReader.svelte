<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { booksApi } from '$lib/api/books';
  import { toastStore } from '$lib/stores/toast';
  import HighlightMenu from './HighlightMenu.svelte';
  import type { HighlightOut } from '$lib/types';

  let { bookId, token, fontFamily = 'serif', fontSize = 16, darkMode = false, onprogress, ontitle, ontoc, ondirection }: {
    bookId: string;
    token: string;
    fontFamily?: string;
    fontSize?: number;
    darkMode?: boolean;
    onprogress?: (detail: { cfi: string; percentage: number; currentPage: number; totalPages: number; pageMapReady: boolean }) => void;
    ontitle?: (title: string) => void;
    ontoc?: (toc: { label: string; href: string; subitems?: any[] }[]) => void;
    ondirection?: (isRtl: boolean) => void;
  } = $props();

  let isRtl = false;

  let container: HTMLDivElement;
  let epubBook: any = $state(null);
  let rendition: any = $state(null);
  let highlights: HighlightOut[] = $state([]);

  // Highlight menu
  let showHighlightMenu = $state(false);
  let highlightMenuX = $state(0);
  let highlightMenuY = $state(0);
  let selectedCfi = $state('');
  let selectedText = $state('');
  let existingHighlight: HighlightOut | null = $state(null);

  // Page tracking — real rendered pages, not character-based estimates
  let sectionPageCounts: number[] = [];
  let pageMapReady = $state(false);
  let currentCfi = '';
  let currentSectionIndex = 0;
  let currentSectionPage = 0;
  let currentPage = 0;
  let totalPages = 0;
  let currentPercentage = 0;

  let progressTimer: ReturnType<typeof setInterval> | null = null;
  let saveDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  let prevFontSize = 0;
  let calculatingPages = false;
  let initialized = false;

  const HIGHLIGHT_COLORS: Record<string, string> = {
    yellow: '#fef08a',
    green: '#bbf7d0',
    blue: '#bfdbfe',
    pink: '#fbcfe8',
    orange: '#fed7aa',
  };

  const SERIF_FONTS = '"Noto Serif CJK TC", "Source Han Serif TC", "Songti TC", "Songti SC", Georgia, "Times New Roman", serif';
  const SANS_FONTS = '"Noto Sans CJK TC", "Source Han Sans TC", "PingFang TC", "PingFang SC", "Microsoft JhengHei", "Microsoft YaHei", system-ui, sans-serif';

  // ── Page map cache ──

  function pageCacheKey(fs: number) {
    return `pageMap:${bookId}:${fs}`;
  }

  function loadCachedPageMap(): number[] | null {
    try {
      const raw = localStorage.getItem(pageCacheKey(fontSize));
      if (!raw) return null;
      const data = JSON.parse(raw);
      if (Array.isArray(data) && data.length > 0) return data;
    } catch {}
    return null;
  }

  function saveCachedPageMap(counts: number[]) {
    try { localStorage.setItem(pageCacheKey(fontSize), JSON.stringify(counts)); } catch {}
  }

  // ── Page computation ──

  function computeAbsolutePage(secIdx: number, displayedPage: number): number {
    let page = 0;
    for (let i = 0; i < secIdx && i < sectionPageCounts.length; i++) {
      page += sectionPageCounts[i];
    }
    return page + displayedPage;
  }

  function computeTotalPages(counts: number[]): number {
    return counts.reduce((a, b) => a + b, 0);
  }

  function emitProgress() {
    onprogress?.({ cfi: currentCfi, percentage: currentPercentage, currentPage, totalPages, pageMapReady });
  }

  // ── Hidden rendition page calculation ──

  async function calculatePageMap(): Promise<number[]> {
    if (calculatingPages) return sectionPageCounts;
    calculatingPages = true;
    try {
      const Epub = (await import('$lib/epubjs/epub.js')).default;
      const hiddenDiv = document.createElement('div');
      hiddenDiv.style.cssText = `position:fixed;left:-9999px;top:0;width:${container.clientWidth}px;height:${container.clientHeight}px;overflow:hidden;`;
      document.body.appendChild(hiddenDiv);

      const hiddenBook = Epub(`/api/books/${bookId}/content/`, { openAs: 'directory' });
      const hiddenRendition = hiddenBook.renderTo(hiddenDiv, {
        width: '100%', height: '100%', spread: 'none',
      });
      hiddenRendition.themes.default({
        body: {
          'font-family': fontFamily === 'serif' ? SERIF_FONTS : SANS_FONTS,
          'font-size': `${fontSize}px`,
          'line-height': '1.8',
          padding: '2rem !important',
        },
      });
      hiddenRendition.themes.select('default');
      await (hiddenBook as any).ready;

      const spineItems = (hiddenBook.spine as any).spineItems;
      const counts: number[] = [];
      for (const item of spineItems) {
        try {
          const total = await new Promise<number>((resolve) => {
            const timeout = setTimeout(() => resolve(1), 5000);
            (hiddenRendition as any).once('relocated', (loc: any) => {
              clearTimeout(timeout);
              resolve(loc?.start?.displayed?.total || 1);
            });
            hiddenRendition.display(item.href).catch(() => { clearTimeout(timeout); resolve(1); });
          });
          counts.push(total);
        } catch { counts.push(1); }
      }

      hiddenRendition.destroy();
      hiddenBook.destroy();
      document.body.removeChild(hiddenDiv);
      return counts;
    } finally {
      calculatingPages = false;
    }
  }

  async function initOrRecalcPageMap() {
    const cached = loadCachedPageMap();
    if (cached) {
      sectionPageCounts = cached;
      totalPages = computeTotalPages(cached);
      pageMapReady = true;
      currentPage = computeAbsolutePage(currentSectionIndex, currentSectionPage);
      currentPercentage = totalPages > 0 ? Math.round((currentPage / totalPages) * 100) : 0;
      emitProgress();
      return;
    }
    pageMapReady = false;
    emitProgress();
    const counts = await calculatePageMap();
    sectionPageCounts = counts;
    totalPages = computeTotalPages(counts);
    pageMapReady = true;
    saveCachedPageMap(counts);
    currentPage = computeAbsolutePage(currentSectionIndex, currentSectionPage);
    currentPercentage = totalPages > 0 ? Math.round((currentPage / totalPages) * 100) : 0;
    emitProgress();
    saveProgress();
  }

  onMount(async () => {
    const Epub = (await import('$lib/epubjs/epub.js')).default;

    // Set token cookie so the browser can authenticate resource requests (images, fonts)
    document.cookie = `token=${token}; path=/; SameSite=Lax`;

    // Use content endpoint as directory — epubjs will fetch individual files from the EPUB
    epubBook = Epub(`/api/books/${bookId}/content/`, {
      openAs: 'directory',
    });

    rendition = epubBook.renderTo(container, {
      width: '100%',
      height: '100%',
      spread: 'none',
    });

    // Apply theme
    applyTheme();

    // relocated handler: use real rendered page counts from displayed.page/total
    rendition.on('relocated', (location: any) => {
      console.log('[relocated] cfi:', location.start.cfi, 'index:', location.start.index, 'displayed.page:', location.start.displayed?.page, '/', location.start.displayed?.total);
      currentCfi = location.start.cfi;
      currentSectionIndex = location.start.index ?? 0;
      currentSectionPage = location.start.displayed?.page ?? 1;
      const sectionTotal = location.start.displayed?.total ?? 1;

      // Update this section's page count from live rendered data
      while (sectionPageCounts.length <= currentSectionIndex) {
        sectionPageCounts.push(1);
      }
      if (sectionPageCounts[currentSectionIndex] !== sectionTotal) {
        sectionPageCounts[currentSectionIndex] = sectionTotal;
        totalPages = computeTotalPages(sectionPageCounts);
      }

      if (pageMapReady) {
        currentPage = computeAbsolutePage(currentSectionIndex, currentSectionPage);
        currentPercentage = totalPages > 0 ? Math.round((currentPage / totalPages) * 100) : 0;
      }

      emitProgress();
      if (pageMapReady) debouncedSave();
    });

    rendition.on('keyup', handleKeyboard);
    document.addEventListener('keyup', handleKeyboard);

    // Scroll wheel navigation inside epub iframe
    rendition.hooks.content.register((contents: any) => {
      const doc = contents.document;
      doc.addEventListener('wheel', handleWheel, { passive: false });
    });
    container.addEventListener('wheel', handleWheel, { passive: false });

    rendition.on('selected', (cfiRange: string, contents: { window: Window }) => {
      const selection = contents.window.getSelection();
      if (!selection || selection.toString().trim() === '') return;
      selectedText = selection.toString().trim();
      selectedCfi = cfiRange;
      existingHighlight = highlights.find((h) => h.cfi_range === cfiRange) ?? null;

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

    // Load highlights
    try {
      highlights = await booksApi.getHighlights(bookId, token);
    } catch {
      // ignore
    }

    // Load saved progress & display
    let savedProgress: any = null;
    try {
      savedProgress = await booksApi.getProgress(bookId, token);
      if (savedProgress?.cfi) {
        // Show saved values immediately while loading
        if (savedProgress.percentage != null) currentPercentage = savedProgress.percentage;
        if (savedProgress.current_page != null) currentPage = savedProgress.current_page;
        if (savedProgress.total_pages != null) totalPages = savedProgress.total_pages;
        emitProgress();

        await rendition.display(savedProgress.cfi);

        // Page-based scroll correction: CFI-based restore loses character offset precision
        // causing off-by-one page errors. After display resolves (manager now exists),
        // override scroll position using the saved section page number.
        if (savedProgress.section_page != null && savedProgress.font_size === fontSize && rendition.manager) {
          const mgr = rendition.manager;
          const targetPage = savedProgress.section_page - 1; // 0-indexed
          mgr._lastTarget = null; // Prevent CFI-based re-scroll in afterResized
          mgr._lastTargetPage = targetPage;
          const distX = targetPage * mgr.layout.delta;
          if (distX + mgr.layout.delta <= mgr.container.scrollWidth) {
            mgr.scrollTo(distX, 0, true);
            mgr._lastTargetPage = null;
          }
          // else: afterResized will handle when scrollWidth expands
        }
      } else {
        await rendition.display();
      }
    } catch {
      await rendition.display();
    }

    // Apply existing highlights
    applyAllHighlights();

    // Get book title & TOC
    epubBook.loaded.metadata.then((meta: { title?: string; direction?: string }) => {
      if (meta.title) ontitle?.(meta.title);
      if (meta.direction === 'rtl') {
        isRtl = true;
        ondirection?.(true);
      }
    });
    epubBook.loaded.navigation.then((nav: { toc: { label: string; href: string; subitems?: any[] }[] }) => {
      ontoc?.(nav.toc);
    });

    // Load page map: try backend cache → localStorage → calculate via hidden rendition
    if (savedProgress?.section_page_counts?.length && savedProgress?.font_size === fontSize) {
      sectionPageCounts = savedProgress.section_page_counts;
      totalPages = computeTotalPages(sectionPageCounts);
      pageMapReady = true;
      currentPage = computeAbsolutePage(currentSectionIndex, currentSectionPage);
      currentPercentage = totalPages > 0 ? Math.round((currentPage / totalPages) * 100) : 0;
      emitProgress();
    } else {
      initOrRecalcPageMap();
    }

    // Save progress every 30s as backup
    progressTimer = setInterval(saveProgress, 30000);
    window.addEventListener('beforeunload', handleBeforeUnload);
    prevFontSize = fontSize;
    initialized = true;
  });

  onDestroy(() => {
    if (progressTimer) clearInterval(progressTimer);
    if (saveDebounceTimer) clearTimeout(saveDebounceTimer);
    saveProgress();
    window.removeEventListener('beforeunload', handleBeforeUnload);
    document.removeEventListener('keyup', handleKeyboard);
    rendition?.destroy();
    epubBook?.destroy();
  });

  function handleBeforeUnload() {
    if (!currentCfi || !pageMapReady) return;
    const data = {
      cfi: currentCfi,
      percentage: currentPercentage,
      current_page: currentPage,
      font_size: fontSize,
      section_index: currentSectionIndex,
      section_page: currentSectionPage,
      section_page_counts: sectionPageCounts,
      total_pages: totalPages,
    };
    fetch(`/api/books/${bookId}/progress`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
      keepalive: true,
    });
  }

  function handleKeyboard(e: KeyboardEvent) {
    if (e.key === 'ArrowLeft') isRtl ? rendition?.next() : rendition?.prev();
    if (e.key === 'ArrowRight') isRtl ? rendition?.prev() : rendition?.next();
  }

  let wheelDebounce = 0;
  function handleWheel(e: WheelEvent) {
    e.preventDefault();
    const now = Date.now();
    if (now - wheelDebounce < 300) return;
    wheelDebounce = now;
    const nextByY = e.deltaY > 0;
    const prevByY = e.deltaY < 0;
    const nextByX = isRtl ? e.deltaX < 0 : e.deltaX > 0;
    const prevByX = isRtl ? e.deltaX > 0 : e.deltaX < 0;
    if (nextByY || nextByX) rendition?.next();
    else if (prevByY || prevByX) rendition?.prev();
  }

  function debouncedSave() {
    if (saveDebounceTimer) clearTimeout(saveDebounceTimer);
    saveDebounceTimer = setTimeout(saveProgress, 2000);
  }

  async function saveProgress() {
    if (!currentCfi || !pageMapReady) return;
    try {
      await booksApi.updateProgress(bookId, {
        cfi: currentCfi,
        percentage: currentPercentage,
        current_page: currentPage,
        font_size: fontSize,
        section_index: currentSectionIndex,
        section_page: currentSectionPage,
        section_page_counts: sectionPageCounts,
        total_pages: totalPages,
      }, token);
    } catch {}
  }

  function applyTheme() {
    if (!rendition) return;
    rendition.themes.default({
      body: {
        'font-family': fontFamily === 'serif' ? SERIF_FONTS : SANS_FONTS,
        'font-size': `${fontSize}px`,
        'line-height': '1.8',
        color: darkMode ? '#e5e7eb' : '#1a1a1a',
        background: darkMode ? '#111827' : '#ffffff',
        padding: '2rem !important',
      },
      '::selection': {
        background: darkMode ? 'rgba(245, 158, 11, 0.4)' : 'rgba(196, 146, 74, 0.3)',
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

  export function displayChapter(href: string) {
    rendition?.display(href);
  }

  $effect(() => {
    fontFamily; fontSize; darkMode;
    if (rendition) {
      applyTheme();
      if (initialized && fontSize !== prevFontSize) {
        prevFontSize = fontSize;
        pageMapReady = false;
        emitProgress();
        initOrRecalcPageMap();
      }
    }
  });

  async function handleHighlightColor(detail: { color: string }) {
    const color = detail.color;
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

  async function handleRemoveHighlight() {
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
        oncolor={handleHighlightColor}
        onremove={handleRemoveHighlight}
        onclose={() => (showHighlightMenu = false)}
      />
    </div>
  {/if}
</div>
