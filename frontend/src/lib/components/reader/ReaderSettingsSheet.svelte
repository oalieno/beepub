<script lang="ts">
  import { Minus, Plus, Sun, Moon } from "@lucide/svelte";

  let {
    open = $bindable(false),
    fontFamily = "serif",
    fontSize = 16,
    darkMode = false,
    isImageBook = false,
    onfontToggle,
    onfontIncrease,
    onfontDecrease,
    onthemeToggle,
  }: {
    open?: boolean;
    fontFamily?: string;
    fontSize?: number;
    darkMode?: boolean;
    isImageBook?: boolean;
    onfontToggle?: () => void;
    onfontIncrease?: () => void;
    onfontDecrease?: () => void;
    onthemeToggle?: () => void;
  } = $props();

  function close() {
    open = false;
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Escape") close();
  }

  const labelClass = $derived(
    darkMode ? "text-gray-400" : "text-muted-foreground",
  );
  const textClass = $derived(darkMode ? "text-gray-200" : "text-foreground");
  const btnClass = $derived(
    darkMode
      ? "border-gray-700 text-gray-300 hover:bg-gray-800"
      : "border-border text-foreground hover:bg-secondary",
  );
  const activeBtnClass = $derived(
    darkMode
      ? "bg-gray-700 text-gray-100 border-gray-600"
      : "bg-foreground text-background border-foreground",
  );
  const inactiveBtnClass = $derived(
    darkMode
      ? "border-gray-700 text-gray-400 hover:bg-gray-800"
      : "border-border text-muted-foreground hover:bg-secondary",
  );
</script>

<svelte:window onkeydown={open ? handleKeydown : undefined} />

{#if open}
  <div
    class="fixed inset-0 z-50 md:hidden"
    role="dialog"
    aria-modal="true"
    aria-label="Reader settings"
  >
    <button
      class="absolute inset-0 bg-black/40"
      aria-label="Close"
      onclick={close}
    ></button>

    <div
      class="absolute bottom-0 left-0 right-0 rounded-t-2xl shadow-2xl animate-slide-up {darkMode
        ? 'bg-gray-900'
        : 'bg-card'}"
      style="padding-bottom: env(safe-area-inset-bottom, 0px);"
    >
      <!-- Drag handle -->
      <div class="flex justify-center pt-3 pb-2">
        <div
          class="w-9 h-1 rounded-full {darkMode
            ? 'bg-gray-700'
            : 'bg-muted-foreground/20'}"
        ></div>
      </div>

      <div class="px-6 pb-6 space-y-5">
        {#if !isImageBook}
          <!-- Font size -->
          <div class="flex items-center justify-between">
            <span class="text-sm {labelClass}">Font size</span>
            <div class="flex items-center gap-3">
              <button
                class="w-8 h-8 flex items-center justify-center rounded-lg border transition-colors {btnClass}"
                onclick={() => onfontDecrease?.()}
                disabled={fontSize <= 10}
                aria-label="Decrease font size"
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
                aria-label="Increase font size"
              >
                <Plus size={14} />
              </button>
            </div>
          </div>

          <!-- Font family -->
          <div class="flex items-center justify-between">
            <span class="text-sm {labelClass}">Font</span>
            <div class="flex gap-1">
              <button
                class="px-4 py-1.5 text-sm font-medium rounded-lg border transition-colors {fontFamily ===
                'sans-serif'
                  ? activeBtnClass
                  : inactiveBtnClass}"
                onclick={() => onfontToggle?.()}
              >
                Sans
              </button>
              <button
                class="px-4 py-1.5 text-sm font-medium rounded-lg border transition-colors {fontFamily ===
                'serif'
                  ? activeBtnClass
                  : inactiveBtnClass}"
                onclick={() => onfontToggle?.()}
              >
                Serif
              </button>
            </div>
          </div>
        {/if}

        <!-- Theme -->
        <div class="flex items-center justify-between">
          <span class="text-sm {labelClass}">Theme</span>
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
              Light
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
              Dark
            </button>
          </div>
        </div>
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
