<script lang="ts">
  import { fly } from "svelte/transition";
  import { toastStore } from "$lib/stores/toast";
  import * as m from "$lib/paraglide/messages.js";
  import { CircleCheck, CircleX, Info, TriangleAlert, X } from "@lucide/svelte";
  import type { ToastType } from "$lib/stores/toast";

  const icons = {
    success: CircleCheck,
    error: CircleX,
    info: Info,
    warning: TriangleAlert,
  } as const;

  // Success is brand-colored (a green card was the only green in the app);
  // the semantic types keep their hue but follow the theme.
  const colors: Record<ToastType, string> = {
    success:
      "bg-[color-mix(in_srgb,var(--primary)_12%,var(--card))] border-primary/40 text-foreground",
    error:
      "bg-red-50 border-red-200 text-red-800 dark:bg-red-950 dark:border-red-900 dark:text-red-200",
    info: "bg-blue-50 border-blue-200 text-blue-800 dark:bg-blue-950 dark:border-blue-900 dark:text-blue-200",
    warning:
      "bg-amber-50 border-amber-200 text-amber-800 dark:bg-amber-950 dark:border-amber-900 dark:text-amber-200",
  };

  // Motion is what catches the eye at the screen's edge; without it a
  // toast appears unnoticed. None for reduced motion.
  const reducedMotion =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const iconColors: Record<ToastType, string> = {
    success: "text-primary",
    error: "",
    info: "",
    warning: "",
  };
</script>

<div
  class="fixed left-1/2 -translate-x-1/2 z-50 flex flex-col items-center gap-2 max-w-sm w-full pointer-events-none px-4 toast-position"
>
  {#each $toastStore as toast (toast.id)}
    {@const IconComponent = icons[toast.type]}
    <div
      class="flex items-start gap-3 px-4 py-3 rounded-2xl border shadow-lg pointer-events-auto w-full {colors[
        toast.type
      ]}"
      role="status"
      in:fly={{ y: 24, duration: reducedMotion ? 0 : 220 }}
      out:fly={{ y: 8, duration: reducedMotion ? 0 : 160 }}
      onpointerenter={() => toastStore.pause(toast.id)}
      onpointerleave={() => toastStore.resume(toast.id)}
    >
      <IconComponent
        size={18}
        class="flex-shrink-0 mt-0.5 {iconColors[toast.type]}"
      />
      <span class="text-sm flex-1 min-w-0 break-words">{toast.message}</span>
      {#if toast.action}
        <button
          class="flex-shrink-0 text-sm font-semibold underline underline-offset-2 hover:opacity-80"
          onclick={() => {
            toast.action?.onclick();
            toastStore.remove(toast.id);
          }}
        >
          {toast.action.label}
        </button>
      {/if}
      <button
        aria-label={m.common_close()}
        class="flex-shrink-0 opacity-70 hover:opacity-100"
        onclick={() => toastStore.remove(toast.id)}
      >
        <X size={16} />
      </button>
    </div>
  {/each}
</div>

<style>
  /* Mobile: above tab bar (56px) + safe area */
  /* --transfer-offset: the transfer panel's height while it shows. */
  /* In the reader, a chapter notice at the bottom (ReaderLoadNotice:
     --reader-notice-height while it shows, above the bottom bar's
     --reader-chrome-offset) keeps its place and the toasts sit above
     it. Without one the second term is far below the screen. */
  .toast-position {
    --above-reader-notice: calc(
      max(env(safe-area-inset-bottom, 0px), var(--reader-chrome-offset, 0px)) +
        1.25rem + var(--reader-notice-height, -100vh)
    );
    bottom: max(
      calc(
        1rem + 56px + env(safe-area-inset-bottom, 0px) +
          var(--transfer-offset, 0px)
      ),
      var(--above-reader-notice)
    );
  }

  /* Desktop: no tab bar, just safe area */
  @media (min-width: 768px) {
    .toast-position {
      bottom: max(
        calc(
          1rem + env(safe-area-inset-bottom, 0px) + var(--transfer-offset, 0px)
        ),
        var(--above-reader-notice)
      );
    }
  }
</style>
