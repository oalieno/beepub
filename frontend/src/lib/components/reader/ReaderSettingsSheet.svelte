<script lang="ts">
  import {
    Minus,
    Plus,
    Sun,
    Moon,
    CircleHelp,
    CloudDownload,
    CloudUpload,
    Loader2,
    File,
    BookOpen,
    GalleryVertical,
    GalleryHorizontal,
    Smartphone,
    ArrowRight,
    ArrowLeft,
  } from "@lucide/svelte";
  import * as m from "$lib/paraglide/messages.js";
  import type { PagerDirection, PagerMode } from "$lib/reader/pages";

  /**
   * The reader's settings sheet. Rows appear when their handler is
   * given, so the two readers share one sheet: the epub.js reader has a
   * single margin preset row (its block axis is fixed), the new engine
   * has two px gutters, letter spacing and a page-turn mode.
   */
  let {
    open = $bindable(false),
    fontFamily = "serif",
    fontSize = 16,
    lineHeight = 1.8,
    letterSpacing = 0,
    pageMargin = 32,
    marginX = 32,
    marginY = 32,
    pageTurn = "instant",
    pageTurnNote = null,
    darkMode = false,
    isImageBook = false,
    pagerMode = "single",
    pagerDirection = "auto",
    pagerShift = false,
    pagerPadding = 0,
    showSync = false,
    syncBusy = null,
    onfontToggle,
    onfontIncrease,
    onfontDecrease,
    onthemeToggle,
    onlineHeightChange,
    onletterSpacingChange,
    onmarginChange,
    onmarginXChange,
    onmarginYChange,
    onpageTurnChange,
    onpagerModeChange,
    onpagerDirectionChange,
    onpagerShiftChange,
    onpagerPaddingChange,
    onhelp,
    onsyncpull,
    onsyncpush,
  }: {
    open?: boolean;
    fontFamily?: string;
    fontSize?: number;
    lineHeight?: number;
    /** px; row shown when `onletterSpacingChange` is given. */
    letterSpacing?: number;
    /** Single inline-padding preset (epub.js reader). */
    pageMargin?: number;
    /** Screen-space gutters, px (new engine); rows shown when their
     *  handlers are given. */
    marginX?: number;
    marginY?: number;
    pageTurn?: "instant" | "animated" | "follow";
    /** Why the mode does not apply to the book on screen (vertical text). */
    pageTurnNote?: string | null;
    darkMode?: boolean;
    isImageBook?: boolean;
    /** Kosync-backed books get manual pull/push controls. */
    showSync?: boolean;
    syncBusy?: "pull" | "push" | null;
    onfontToggle?: () => void;
    onfontIncrease?: () => void;
    onfontDecrease?: () => void;
    onthemeToggle?: () => void;
    onlineHeightChange?: (value: number) => void;
    onletterSpacingChange?: (value: number) => void;
    onmarginChange?: (value: number) => void;
    onmarginXChange?: (value: number) => void;
    onmarginYChange?: (value: number) => void;
    onpageTurnChange?: (value: "instant" | "animated" | "follow") => void;
    /** Image pager rows (comics): reading mode, direction, double-page
     *  pairing and page padding. Present only while the pager renders. */
    pagerMode?: PagerMode;
    pagerDirection?: PagerDirection;
    pagerShift?: boolean;
    /** px kept around the pages. */
    pagerPadding?: number;
    onpagerModeChange?: (value: PagerMode) => void;
    onpagerDirectionChange?: (value: PagerDirection) => void;
    onpagerShiftChange?: (value: boolean) => void;
    onpagerPaddingChange?: (value: number) => void;
    onhelp?: () => void;
    onsyncpull?: () => void;
    onsyncpush?: () => void;
  } = $props();

  function close() {
    open = false;
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Escape") close();
  }

  const labelClass = $derived(
    darkMode ? "text-ink-400" : "text-muted-foreground",
  );
  const textClass = $derived(darkMode ? "text-ink-200" : "text-foreground");
  const btnClass = $derived(
    darkMode
      ? "border-ink-700 text-ink-300 hover:bg-ink-800 disabled:opacity-40"
      : "border-border text-foreground hover:bg-secondary disabled:opacity-40",
  );
  // The sheet sits inside the reader root, so bg-primary resolves to the
  // .reader-dark gold — a solid selected state to match the light theme's,
  // instead of the one-step-of-gray that was hard to spot.
  const activeBtnClass = $derived(
    darkMode
      ? "bg-primary text-primary-foreground border-primary"
      : "bg-foreground text-background border-foreground",
  );
  const inactiveBtnClass = $derived(
    darkMode
      ? "border-ink-700 text-ink-400 hover:bg-ink-800"
      : "border-border text-muted-foreground hover:bg-secondary",
  );
  const lineHeightOptions = [
    { value: 1.5, label: m.reader_line_compact },
    { value: 1.8, label: m.reader_line_normal },
    { value: 2.2, label: m.reader_line_relaxed },
  ];
  const marginOptions = [
    { value: 16, label: m.reader_margin_narrow },
    { value: 32, label: m.reader_margin_normal },
    { value: 56, label: m.reader_margin_wide },
  ];
  const pageTurnOptions: {
    value: "instant" | "animated" | "follow";
    label: () => string;
  }[] = [
    { value: "instant", label: m.reader_page_turn_instant },
    { value: "animated", label: m.reader_page_turn_slide },
    { value: "follow", label: m.reader_page_turn_follow },
  ];
  const pagerModeOptions: {
    value: PagerMode;
    label: () => string;
    icon: typeof File;
  }[] = [
    { value: "single", label: m.reader_pager_mode_single, icon: File },
    { value: "double", label: m.reader_pager_mode_double, icon: BookOpen },
    {
      value: "vertical",
      label: m.reader_pager_mode_vertical,
      icon: GalleryVertical,
    },
    {
      value: "horizontal",
      label: m.reader_pager_mode_horizontal,
      icon: GalleryHorizontal,
    },
    { value: "webtoon", label: m.reader_pager_mode_webtoon, icon: Smartphone },
  ];
  const pagerShiftOptions: { value: boolean; label: () => string }[] = [
    { value: false, label: m.reader_pager_pairing_cover },
    { value: true, label: m.reader_pager_pairing_shift },
  ];
  const pagerDirectionOptions: {
    value: PagerDirection;
    label: () => string;
    icon: typeof File | null;
  }[] = [
    { value: "auto", label: m.reader_pager_direction_auto, icon: null },
    { value: "ltr", label: m.reader_pager_direction_ltr, icon: ArrowRight },
    { value: "rtl", label: m.reader_pager_direction_rtl, icon: ArrowLeft },
  ];

  // Gutters step in 8px; letter spacing in half pixels (sub-pixel
  // spacing renders fine — text is positioned at sub-pixel precision).
  const MARGIN_STEP = 8;
  const MARGIN_MAX = 96;
  const LETTER_STEP = 0.5;
  const LETTER_MAX = 4;

  function stepTo(value: number, step: number, dir: 1 | -1, max: number) {
    // Snap to the grid first so a migrated or odd stored value lands on
    // a step rather than drifting beside it.
    const next = (Math.round(value / step) + dir) * step;
    return Math.min(max, Math.max(0, Math.round(next * 100) / 100));
  }

  const showGutters = $derived(!!onmarginXChange || !!onmarginYChange);
</script>

<svelte:window onkeydown={open ? handleKeydown : undefined} />

{#snippet stepper(opts: {
  name: string;
  testid: string;
  value: number;
  display: string;
  step: number;
  max: number;
  onchange: (value: number) => void;
})}
  <div class="flex items-center justify-between">
    <span class="text-sm {labelClass}">{opts.name}</span>
    <div class="flex items-center gap-3">
      <button
        class="w-8 h-8 flex items-center justify-center rounded-lg border transition-colors {btnClass}"
        onclick={() =>
          opts.onchange(stepTo(opts.value, opts.step, -1, opts.max))}
        disabled={opts.value <= 0}
        aria-label={m.reader_step_down({ setting: opts.name })}
      >
        <Minus size={14} />
      </button>
      <span
        class="text-sm font-medium w-12 text-center tabular-nums {textClass}"
        data-testid={opts.testid}>{opts.display}</span
      >
      <button
        class="w-8 h-8 flex items-center justify-center rounded-lg border transition-colors {btnClass}"
        onclick={() =>
          opts.onchange(stepTo(opts.value, opts.step, 1, opts.max))}
        disabled={opts.value >= opts.max}
        aria-label={m.reader_step_up({ setting: opts.name })}
      >
        <Plus size={14} />
      </button>
    </div>
  </div>
{/snippet}

{#if open}
  <div
    class="fixed inset-0 z-50"
    role="dialog"
    aria-modal="true"
    aria-label={m.reader_settings_title()}
  >
    <button
      class="absolute inset-0 bg-black/40"
      aria-label={m.common_close()}
      onclick={close}
    ></button>

    <div
      class="absolute bottom-0 left-0 right-0 rounded-t-2xl shadow-2xl animate-slide-up md:bottom-8 md:left-1/2 md:right-auto md:w-[400px] md:-translate-x-1/2 md:rounded-2xl {darkMode
        ? 'bg-ink-900'
        : 'bg-card'}"
      style="padding-bottom: env(safe-area-inset-bottom, 0px);"
    >
      <!-- Drag handle -->
      <div class="flex justify-center pt-3 pb-2 md:hidden">
        <div
          class="w-9 h-1 rounded-full {darkMode
            ? 'bg-ink-700'
            : 'bg-muted-foreground/20'}"
        ></div>
      </div>

      <div class="px-6 pb-6 md:pt-6 space-y-5">
        {#if !isImageBook}
          <!-- Font size -->
          <div class="flex items-center justify-between">
            <span class="text-sm {labelClass}">{m.reader_font_size()}</span>
            <div class="flex items-center gap-3">
              <button
                class="w-8 h-8 flex items-center justify-center rounded-lg border transition-colors {btnClass}"
                onclick={() => onfontDecrease?.()}
                disabled={fontSize <= 10}
                aria-label={m.reader_decrease_font()}
              >
                <Minus size={14} />
              </button>
              <span
                class="text-sm font-medium w-12 text-center tabular-nums {textClass}"
                data-testid="setting-font-size">{fontSize}px</span
              >
              <button
                class="w-8 h-8 flex items-center justify-center rounded-lg border transition-colors {btnClass}"
                onclick={() => onfontIncrease?.()}
                disabled={fontSize >= 32}
                aria-label={m.reader_increase_font()}
              >
                <Plus size={14} />
              </button>
            </div>
          </div>

          <!-- Font family -->
          <div class="flex items-center justify-between">
            <span class="text-sm {labelClass}">{m.reader_font()}</span>
            <div class="flex gap-1">
              <button
                class="px-4 py-1.5 text-sm font-medium rounded-lg border transition-colors {fontFamily ===
                'sans-serif'
                  ? activeBtnClass
                  : inactiveBtnClass}"
                onclick={() => {
                  if (fontFamily !== "sans-serif") onfontToggle?.();
                }}
              >
                {m.reader_font_sans()}
              </button>
              <button
                class="px-4 py-1.5 text-sm font-medium rounded-lg border transition-colors {fontFamily ===
                'serif'
                  ? activeBtnClass
                  : inactiveBtnClass}"
                onclick={() => {
                  if (fontFamily !== "serif") onfontToggle?.();
                }}
              >
                {m.reader_font_serif()}
              </button>
            </div>
          </div>

          {#if onletterSpacingChange}
            {@render stepper({
              name: m.reader_letter_spacing(),
              testid: "setting-letter-spacing",
              value: letterSpacing,
              display: `${letterSpacing}px`,
              step: LETTER_STEP,
              max: LETTER_MAX,
              onchange: onletterSpacingChange,
            })}
          {/if}

          <!-- Line spacing -->
          <div class="flex items-center justify-between">
            <span class="text-sm {labelClass}">{m.reader_line_height()}</span>
            <div class="flex gap-1">
              {#each lineHeightOptions as option}
                <button
                  class="px-3 py-1.5 text-sm font-medium rounded-lg border transition-colors {lineHeight ===
                  option.value
                    ? activeBtnClass
                    : inactiveBtnClass}"
                  onclick={() => onlineHeightChange?.(option.value)}
                >
                  {option.label()}
                </button>
              {/each}
            </div>
          </div>

          {#if showGutters}
            {#if onmarginYChange}
              {@render stepper({
                name: m.reader_margin_y(),
                testid: "setting-margin-y",
                value: marginY,
                display: `${marginY}px`,
                step: MARGIN_STEP,
                max: MARGIN_MAX,
                onchange: onmarginYChange,
              })}
            {/if}
            {#if onmarginXChange}
              {@render stepper({
                name: m.reader_margin_x(),
                testid: "setting-margin-x",
                value: marginX,
                display: `${marginX}px`,
                step: MARGIN_STEP,
                max: MARGIN_MAX,
                onchange: onmarginXChange,
              })}
            {/if}
          {:else if onmarginChange}
            <!-- Margins (single inline-padding preset) -->
            <div class="flex items-center justify-between">
              <span class="text-sm {labelClass}">{m.reader_margin()}</span>
              <div class="flex gap-1">
                {#each marginOptions as option}
                  <button
                    class="px-3 py-1.5 text-sm font-medium rounded-lg border transition-colors {pageMargin ===
                    option.value
                      ? activeBtnClass
                      : inactiveBtnClass}"
                    onclick={() => onmarginChange?.(option.value)}
                  >
                    {option.label()}
                  </button>
                {/each}
              </div>
            </div>
          {/if}
        {/if}

        {#if onpageTurnChange}
          <div class="flex items-center justify-between">
            <span class="text-sm {labelClass}">{m.reader_page_turn()}</span>
            <div class="flex gap-1">
              {#each pageTurnOptions as option}
                <button
                  class="px-3 py-1.5 text-sm font-medium rounded-lg border transition-colors {pageTurn ===
                  option.value
                    ? activeBtnClass
                    : inactiveBtnClass}"
                  onclick={() => onpageTurnChange?.(option.value)}
                >
                  {option.label()}
                </button>
              {/each}
            </div>
          </div>
          {#if pageTurnNote}
            <p class="-mt-2 text-xs {labelClass}">{pageTurnNote}</p>
          {/if}
        {/if}

        {#if onpagerModeChange}
          <!-- Image pager: reading mode. Label left, choices right like
               every other row; five choices fit only as icons, so the
               selected one alone shows its name. -->
          <div class="flex flex-wrap items-center justify-between gap-2">
            <span class="shrink-0 text-sm {labelClass}"
              >{m.reader_pager_mode()}</span
            >
            <div class="ml-auto flex gap-1" data-testid="setting-pager-mode">
              {#each pagerModeOptions as option}
                {@const active = pagerMode === option.value}
                <button
                  class="flex h-9 items-center gap-1.5 whitespace-nowrap rounded-lg border text-sm font-medium transition-colors {active
                    ? `px-3 ${activeBtnClass}`
                    : `w-9 justify-center ${inactiveBtnClass}`}"
                  aria-label={option.label()}
                  title={option.label()}
                  onclick={() => onpagerModeChange?.(option.value)}
                >
                  <option.icon size={16} />
                  {#if active}
                    {option.label()}
                  {/if}
                </button>
              {/each}
            </div>
          </div>
          {#if onpagerDirectionChange}
            <!-- The three chips outgrow a phone-width row in English:
                 they drop under the label, right-aligned, rather than
                 wrapping their words. -->
            <div class="flex flex-wrap items-center justify-between gap-2">
              <span class="shrink-0 text-sm {labelClass}"
                >{m.reader_pager_direction()}</span
              >
              <div
                class="ml-auto flex gap-1"
                data-testid="setting-pager-direction"
              >
                {#each pagerDirectionOptions as option}
                  <button
                    class="flex items-center gap-1.5 whitespace-nowrap px-3 py-1.5 text-sm font-medium rounded-lg border transition-colors {pagerDirection ===
                    option.value
                      ? activeBtnClass
                      : inactiveBtnClass}"
                    onclick={() => onpagerDirectionChange?.(option.value)}
                  >
                    {#if option.icon}
                      <option.icon size={14} />
                    {/if}
                    {option.label()}
                  </button>
                {/each}
              </div>
            </div>
          {/if}
          {#if onpagerShiftChange && pagerMode === "double"}
            <!-- Which pages sit together: cover alone (1 | 2–3) or shifted
                 by one (1–2 | 3–4), for a file without its cover. -->
            <div class="flex items-center justify-between gap-3">
              <span class="shrink-0 text-sm {labelClass}"
                >{m.reader_pager_pairing()}</span
              >
              <div class="flex gap-1" data-testid="setting-pager-shift">
                {#each pagerShiftOptions as option}
                  <button
                    class="whitespace-nowrap px-3 py-1.5 text-sm font-medium rounded-lg border transition-colors {pagerShift ===
                    option.value
                      ? activeBtnClass
                      : inactiveBtnClass}"
                    onclick={() => onpagerShiftChange?.(option.value)}
                  >
                    {option.label()}
                  </button>
                {/each}
              </div>
            </div>
          {/if}
          {#if onpagerPaddingChange}
            {@render stepper({
              name: m.reader_pager_padding(),
              testid: "setting-pager-padding",
              value: pagerPadding,
              display: `${pagerPadding}px`,
              step: MARGIN_STEP,
              max: MARGIN_MAX,
              onchange: onpagerPaddingChange,
            })}
          {/if}
        {/if}

        <!-- Theme -->
        <div class="flex items-center justify-between">
          <span class="text-sm {labelClass}">{m.reader_theme()}</span>
          <div class="flex gap-1">
            <button
              class="flex items-center gap-1.5 px-4 py-1.5 text-sm font-medium rounded-lg border transition-colors {!darkMode
                ? activeBtnClass
                : inactiveBtnClass}"
              onclick={() => {
                if (darkMode) onthemeToggle?.();
              }}
            >
              <Sun size={14} />
              {m.reader_theme_light()}
            </button>
            <button
              class="flex items-center gap-1.5 px-4 py-1.5 text-sm font-medium rounded-lg border transition-colors {darkMode
                ? activeBtnClass
                : inactiveBtnClass}"
              onclick={() => {
                if (!darkMode) onthemeToggle?.();
              }}
            >
              <Moon size={14} />
              {m.reader_theme_dark()}
            </button>
          </div>
        </div>

        {#if showSync}
          <!-- Manual kosync sync -->
          <div class="flex items-center justify-between">
            <span class="text-sm {labelClass}">{m.kosync_title()}</span>
            <div class="flex gap-1">
              <button
                class="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg border transition-colors {btnClass}"
                disabled={syncBusy !== null}
                onclick={() => onsyncpull?.()}
              >
                {#if syncBusy === "pull"}
                  <Loader2 size={14} class="animate-spin" />
                {:else}
                  <CloudDownload size={14} />
                {/if}
                {m.kosync_pull()}
              </button>
              <button
                class="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg border transition-colors {btnClass}"
                disabled={syncBusy !== null}
                onclick={() => onsyncpush?.()}
              >
                {#if syncBusy === "push"}
                  <Loader2 size={14} class="animate-spin" />
                {:else}
                  <CloudUpload size={14} />
                {/if}
                {m.kosync_push()}
              </button>
            </div>
          </div>
        {/if}

        <!-- Gesture help -->
        {#if onhelp}
          <button
            class="flex items-center gap-2 text-sm {labelClass}"
            onclick={() => {
              close();
              onhelp?.();
            }}
          >
            <CircleHelp size={16} />
            {m.reader_gesture_help()}
          </button>
        {/if}
      </div>
    </div>
  </div>
{/if}

<style>
  @keyframes slide-up {
    from {
      transform: translateY(100%);
    }
    to {
      transform: translateY(0);
    }
  }
  .animate-slide-up {
    animation: slide-up 0.2s ease-out;
  }
</style>
