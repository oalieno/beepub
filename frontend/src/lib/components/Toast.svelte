<script lang="ts">
  import { toastStore } from '$lib/stores/toast';
  import { CheckCircle, XCircle, Info, AlertTriangle, X } from 'lucide-svelte';

  const icons = {
    success: CheckCircle,
    error: XCircle,
    info: Info,
    warning: AlertTriangle,
  };

  const colors = {
    success: 'bg-green-800 border-green-600 text-green-100',
    error: 'bg-red-800 border-red-600 text-red-100',
    info: 'bg-blue-800 border-blue-600 text-blue-100',
    warning: 'bg-yellow-800 border-yellow-600 text-yellow-100',
  };
</script>

<div class="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none">
  {#each $toastStore as toast (toast.id)}
    <div
      class="flex items-start gap-3 px-4 py-3 rounded-lg border shadow-lg pointer-events-auto {colors[toast.type]}"
    >
      <svelte:component this={icons[toast.type]} size={18} class="flex-shrink-0 mt-0.5" />
      <span class="text-sm flex-1">{toast.message}</span>
      <button
        class="flex-shrink-0 opacity-70 hover:opacity-100"
        on:click={() => toastStore.remove(toast.id)}
      >
        <X size={16} />
      </button>
    </div>
  {/each}
</div>
