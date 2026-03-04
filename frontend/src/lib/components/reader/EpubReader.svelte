<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { booksApi } from '$lib/api/books';
  import { toastStore } from '$lib/stores/toast';
  import HighlightMenu from './HighlightMenu.svelte';
  import type { HighlightOut } from '$lib/types';

  let { bookId, token, fontFamily = 'serif', fontSize = 16, darkMode = false, onprogress, ontitle, ontoc, ondirection, onhighlightschange }: {
    bookId: string;
    token: string;
    fontFamily?: string;
    fontSize?: number;
    darkMode?: boolean;
    onprogress?: (detail: { cfi: string; percentage: number }) => void;
    ontitle?: (title: string) => void;
    ontoc?: (toc: { label: string; href: string; subitems?: any[] }[]) => void;
    ondirection?: (isRtl: boolean) => void;
    onhighlightschange?: (highlights: HighlightOut[]) => void;
  } = $props();

  let isRtl = $state(false);

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

  // Footnote popup
  let showFootnote = $state(false);
  let footnoteContent = $state('');
  let footnoteOpenedThisClick = false;
  let footnoteSourcePath = '';

  // Progress tracking
  let currentCfi = '';
  let currentSectionIndex = 0;
  let currentSectionPage = 0;
  let currentPercentage = 0;

  let progressTimer: ReturnType<typeof setInterval> | null = null;
  let saveDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  let prevFontSize = 0;
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

  function emitProgress() {
    onprogress?.({ cfi: currentCfi, percentage: currentPercentage });
  }

  function normalizeFootnoteHref(rawHref: string): string | null {
    const href = (rawHref ?? '').trim();
    if (!href || href.startsWith('javascript:')) return null;

    // Resolve popup links against the original section path of this footnote,
    // then map them back to epub.js-relative spine hrefs.
    const basePath = footnoteSourcePath || '';
    const baseUrl = `https://epub.local/${basePath}`;
    const resolved = new URL(href, baseUrl);

    if (resolved.origin !== 'https://epub.local') return null;

    const path = resolved.pathname.replace(/^\/+/, '');
    const hash = resolved.hash || '';
    return path || hash ? `${path}${hash}` : null;
  }

  async function handleFootnoteContentClick(e: MouseEvent) {
    const target = e.target as HTMLElement | null;
    const anchor = target?.closest?.('a') as HTMLAnchorElement | null;
    if (!anchor) return;

    const hrefAttr = anchor.getAttribute('href') ?? '';
    const normalized = normalizeFootnoteHref(hrefAttr);
    if (!normalized) return;

    e.preventDefault();
    showFootnote = false;
    await rendition?.display(normalized);
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

    // relocated handler: calculate percentage from section position
    rendition.on('relocated', (location: any) => {
      currentCfi = location.start.cfi;
      currentSectionIndex = location.start.index ?? 0;
      currentSectionPage = location.start.displayed?.page ?? 1;
      const displayedTotal = location.start.displayed?.total ?? 1;
      const totalSections = epubBook?.spine?.spineItems?.length ?? 1;
      currentPercentage = Math.min(100, Math.max(0, Math.round(
        ((currentSectionIndex + currentSectionPage / displayedTotal) / totalSections) * 100
      )));
      emitProgress();
      debouncedSave();
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
      const text = selection.toString().trim();
      const existing = highlights.find((h) => h.cfi_range === cfiRange) ?? null;

      const range = selection.getRangeAt(0);
      const rect = range.getBoundingClientRect();

      // rect is relative to the iframe element's origin (top-left of the full-width iframe).
      // In paginated mode the iframe is wider than the visible area (covers all CSS columns).
      // The epub-container (rendition.manager.container) scrolls horizontally to show the
      // current page. Subtract scrollLeft to get the position within the visible area.
      const mgr = rendition?.manager;
      const scrollLeft = mgr?.container?.scrollLeft ?? 0;
      const scrollTop = mgr?.container?.scrollTop ?? 0;
      const x = rect.left - scrollLeft + rect.width / 2;
      const y = rect.top - scrollTop - 8;

      selectedCfi = cfiRange;
      selectedText = text;
      existingHighlight = existing;
      highlightMenuX = x;
      highlightMenuY = y;
      showHighlightMenu = true;
    });

    rendition.on('click', () => {
      // Only dismiss highlight menu if there's no active text selection
      // (the 'selected' event fires after 'click' due to debounce, so avoid race)
      const contents = rendition?.manager?.getContents?.();
      const sel = contents?.[0]?.window?.getSelection();
      if (!sel || sel.isCollapsed || sel.toString().trim() === '') {
        showHighlightMenu = false;
        // Don't close footnote if it was just opened by a link click in the same event cycle
        if (!footnoteOpenedThisClick) {
          showFootnote = false;
        }
      }
    });

    rendition.on('link', async (linkEvent: any) => {
      const href: string = linkEvent.href;
      const hashIdx = href.indexOf('#');
      console.log('[link] href:', href, 'hashIdx:', hashIdx, 'isRtl:', isRtl);
      if (hashIdx === -1) {
        console.log('[link] no hash, letting default handleLinks run');
        return;
      }

      const filePath = href.slice(0, hashIdx);
      const elementId = href.slice(hashIdx + 1);

      const section = epubBook.spine.get(filePath);
      console.log('[link] filePath:', filePath, 'elementId:', elementId, 'section found:', !!section, 'section.index:', section?.index);
      if (!section) return;

      // Prevent default synchronously — async handler can't prevent after await
      linkEvent.preventDefault();
      // Flag to prevent the click handler (same event cycle) from closing the popup
      footnoteOpenedThisClick = true;
      setTimeout(() => { footnoteOpenedThisClick = false; }, 0);

      try {
        // Fetch section HTML independently (don't use section.load() which corrupts spine state)
        const sectionUrl = section.url;
        const response = await fetch(sectionUrl);
        const html = await response.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'application/xhtml+xml');
        const el = doc.querySelector(`#${CSS.escape(elementId)}`);

        // Check if the target element has meaningful text content (not just a number/marker)
        const textLen = (el?.textContent ?? '').trim().length;
        console.log('[link] el found:', !!el, 'textLen:', textLen, 'tagName:', el?.tagName, 'text preview:', (el?.textContent ?? '').trim().slice(0, 50));
        if (!el || textLen < 2) {
          // Back-reference link or empty target — navigate instead of popup
          console.log('[link] back-reference → display()', href);
          const mgr = rendition?.manager;
          console.log('[link] BEFORE display: scrollLeft:', mgr?.container?.scrollLeft, 'scrollWidth:', mgr?.container?.scrollWidth, 'direction:', mgr?.settings?.direction);
          await rendition?.display(href);
          const mgr2 = rendition?.manager;
          console.log('[link] AFTER display: scrollLeft:', mgr2?.container?.scrollLeft, 'scrollWidth:', mgr2?.container?.scrollWidth);
          return;
        }

        footnoteSourcePath = filePath;
        footnoteContent = el.innerHTML;
        showFootnote = true;
      } catch (err) {
        console.error('[link] error:', err);
        await rendition?.display(href);
      }
    });

    // Load highlights
    try {
      highlights = await booksApi.getHighlights(bookId, token);
      onhighlightschange?.(highlights);
    } catch {
      // ignore
    }

    // Load saved progress & display
    let savedProgress: any = null;
    try {
      savedProgress = await booksApi.getProgress(bookId, token);
      if (savedProgress?.cfi) {
        // Show saved percentage immediately while loading
        if (savedProgress.percentage != null) currentPercentage = savedProgress.percentage;
        emitProgress();

        await rendition.display(savedProgress.cfi);

        // Page-based scroll correction: CFI-based restore loses character offset precision
        // causing off-by-one page errors. After display resolves (manager now exists),
        // override scroll position using the saved section page number.
        if (savedProgress.section_page != null && savedProgress.font_size === fontSize && rendition.manager) {
          const mgr = rendition.manager;
          const targetPage = Math.max(0, savedProgress.section_page - 1); // 0-indexed
          mgr._lastTarget = null; // Prevent CFI-based re-scroll in afterResized
          mgr._lastTargetPage = targetPage;
          if (typeof mgr.scrollToPageIndex === 'function' && mgr.scrollToPageIndex(targetPage)) {
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
    if (!currentCfi) return;
    const data = {
      cfi: currentCfi,
      percentage: currentPercentage,
      font_size: fontSize,
      section_index: currentSectionIndex,
      section_page: currentSectionPage,
    };
    fetch(`/api/books/${bookId}/progress`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
      keepalive: true,
    });
  }

  function handleKeyboard(e: KeyboardEvent) {
    showFootnote = false;
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
    if (nextByY || nextByX) { showFootnote = false; rendition?.next(); }
    else if (prevByY || prevByX) { showFootnote = false; rendition?.prev(); }
  }

  function handleLeftTapNav() {
    if (showFootnote || showHighlightMenu) return;
    showFootnote = false;
    isRtl ? rendition?.next() : rendition?.prev();
  }

  function handleRightTapNav() {
    if (showFootnote || showHighlightMenu) return;
    showFootnote = false;
    isRtl ? rendition?.prev() : rendition?.next();
  }

  function debouncedSave() {
    if (saveDebounceTimer) clearTimeout(saveDebounceTimer);
    saveDebounceTimer = setTimeout(saveProgress, 2000);
  }

  async function saveProgress() {
    if (!currentCfi) return;
    try {
      await booksApi.updateProgress(bookId, {
        cfi: currentCfi,
        percentage: currentPercentage,
        font_size: fontSize,
        section_index: currentSectionIndex,
        section_page: currentSectionPage,
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
        '-webkit-text-size-adjust': '100%',
        'text-size-adjust': '100%',
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
    showFootnote = false;
    rendition?.prev();
  }

  export function next() {
    showFootnote = false;
    rendition?.next();
  }

  export function displayChapter(href: string) {
    rendition?.display(href);
  }

  export function displayCfi(cfi: string) {
    rendition?.display(cfi);
  }

  export function removeHighlightAnnotation(cfiRange: string) {
    rendition?.annotations.remove(cfiRange, 'highlight');
  }

  $effect(() => {
    fontFamily; fontSize; darkMode;
    if (rendition) {
      applyTheme();
      if (initialized && fontSize !== prevFontSize) {
        prevFontSize = fontSize;
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
      onhighlightschange?.(highlights);
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
      onhighlightschange?.(highlights);
      toastStore.success('Highlight removed');
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }
</script>

<div class="relative w-full h-full overflow-hidden touch-pan-x {darkMode ? 'bg-gray-900' : 'bg-white'}">
  <div bind:this={container} class="w-full h-full overflow-hidden {darkMode ? 'bg-gray-900' : 'bg-white'}"></div>

  <button
    type="button"
    class="absolute inset-y-0 left-0 z-10 w-20 sm:w-20 md:w-24"
    aria-label="Previous page"
    onclick={handleLeftTapNav}
  ></button>
  <button
    type="button"
    class="absolute inset-y-0 right-0 z-10 w-20 sm:w-20 md:w-24"
    aria-label="Next page"
    onclick={handleRightTapNav}
  ></button>

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

  {#if showFootnote}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="absolute inset-0 z-50 flex items-center justify-center"
      onclick={() => (showFootnote = false)}
    >
      <div
        class="footnote-content rounded-lg shadow-2xl p-8 leading-relaxed {darkMode ? 'bg-gray-800 text-gray-200 border-2 border-gray-500' : 'bg-white text-gray-900 border-2 border-black'}"
        style="width: 50%; height: 50%; overflow-y: auto; font-size: {fontSize}px;{isRtl ? ' writing-mode: vertical-rl; max-height: none; overflow-x: auto; overflow-y: hidden;' : ''}"
        onclick={async (e: MouseEvent) => { e.stopPropagation(); await handleFootnoteContentClick(e); }}
      >
        {@html footnoteContent}
      </div>
    </div>
  {/if}
</div>

<style>
  :global(.footnote-content a),
  :global(.footnote-content sup) {
    text-orientation: upright;
    text-combine-upright: all;
  }
</style>
