<script lang="ts">
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
  .toast-position {
    bottom: calc(1rem + 56px + env(safe-area-inset-bottom, 0px));
  }

  /* Desktop: no tab bar, just safe area */
  @media (min-width: 768px) {
    .toast-position {
      bottom: calc(1rem + env(safe-area-inset-bottom, 0px));
    }
  }
</style>
