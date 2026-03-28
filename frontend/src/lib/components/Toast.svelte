<script lang="ts">
  import { toastStore } from "$lib/stores/toast";
  import { CheckCircle, XCircle, Info, AlertTriangle, X } from "@lucide/svelte";
  import type { ToastType } from "$lib/stores/toast";

  const icons = {
    success: CheckCircle,
    error: XCircle,
    info: Info,
    warning: AlertTriangle,
  } as const;

  const colors: Record<ToastType, string> = {
    success: "bg-emerald-50 border-emerald-200 text-emerald-800",
    error: "bg-red-50 border-red-200 text-red-800",
    info: "bg-blue-50 border-blue-200 text-blue-800",
    warning: "bg-amber-50 border-amber-200 text-amber-800",
  };
</script>

<div
  class="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none"
>
  {#each $toastStore as toast (toast.id)}
    {@const IconComponent = icons[toast.type]}
    <div
      class="flex items-start gap-3 px-4 py-3 rounded-2xl border shadow-lg pointer-events-auto {colors[
        toast.type
      ]}"
    >
      <IconComponent size={18} class="flex-shrink-0 mt-0.5" />
      <span class="text-sm flex-1">{toast.message}</span>
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
        class="flex-shrink-0 opacity-70 hover:opacity-100"
        onclick={() => toastStore.remove(toast.id)}
      >
        <X size={16} />
      </button>
    </div>
  {/each}
</div>
