<script lang="ts">
  import { Minus, Plus, Sun, Moon, CircleHelp } from "@lucide/svelte";
  import * as m from "$lib/paraglide/messages.js";

  let {
    open = $bindable(false),
    fontFamily = "serif",
    fontSize = 16,
    lineHeight = 1.8,
    pageMargin = 32,
    darkMode = false,
    isImageBook = false,
    onfontToggle,
    onfontIncrease,
    onfontDecrease,
    onthemeToggle,
    onlineHeightChange,
    onmarginChange,
    onhelp,
  }: {
    open?: boolean;
    fontFamily?: string;
    fontSize?: number;
    lineHeight?: number;
    pageMargin?: number;
    darkMode?: boolean;
    isImageBook?: boolean;
    onfontToggle?: () => void;
    onfontIncrease?: () => void;
    onfontDecrease?: () => void;
    onthemeToggle?: () => void;
    onlineHeightChange?: (value: number) => void;
    onmarginChange?: (value: number) => void;
    onhelp?: () => void;
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
      ? "border-ink-700 text-ink-300 hover:bg-ink-800"
      : "border-border text-foreground hover:bg-secondary",
  );
  const activeBtnClass = $derived(
    darkMode
      ? "bg-ink-700 text-ink-100 border-ink-600"
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
</script>

<svelte:window onkeydown={open ? handleKeydown : undefined} />

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
              <span class="text-sm font-medium w-10 text-center {textClass}"
                >{fontSize}px</span
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
                onclick={() => onfontToggle?.()}
              >
                {m.reader_font_sans()}
              </button>
              <button
                class="px-4 py-1.5 text-sm font-medium rounded-lg border transition-colors {fontFamily ===
                'serif'
                  ? activeBtnClass
                  : inactiveBtnClass}"
                onclick={() => onfontToggle?.()}
              >
                {m.reader_font_serif()}
              </button>
            </div>
          </div>
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

          <!-- Margins -->
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

        <!-- Gesture help -->
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
