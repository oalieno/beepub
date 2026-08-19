<script lang="ts">
  import { CloudOff } from "@lucide/svelte";
  import { switchAppMode } from "$lib/api/client";
  import { Button } from "$lib/components/ui/button";
  import { checkServerNow } from "$lib/services/network";
  import { toastStore } from "$lib/stores/toast";
  import * as m from "$lib/paraglide/messages.js";

  let checking = $state(false);

  async function retry() {
    checking = true;
    try {
      const ok = await checkServerNow();
      if (!ok) {
        toastStore.error(m.error_server_unreachable());
      }
      // On success isOnline flips and the layout swaps this screen out.
    } finally {
      checking = false;
    }
  }
</script>

<div
  role="status"
  class="min-h-screen flex items-center justify-center px-6"
  style="padding-top: env(safe-area-inset-top, 0px); padding-bottom: env(safe-area-inset-bottom, 0px);"
>
  <div class="w-full max-w-sm text-center">
    <div
      class="w-16 h-16 rounded-2xl bg-muted flex items-center justify-center mx-auto mb-4"
    >
      <CloudOff size={28} class="text-muted-foreground" />
    </div>
    <h1 class="text-lg font-semibold mb-1">{m.error_server_unreachable()}</h1>
    <p class="text-sm text-muted-foreground mb-6">{m.disconnect_hint()}</p>
    <div class="space-y-2">
      <Button
        class="w-full rounded-xl h-11"
        disabled={checking}
        onclick={retry}
      >
        {checking ? m.home_offline_checking() : m.home_offline_retry()}
      </Button>
      <Button
        variant="outline"
        class="w-full rounded-xl h-11"
        onclick={() => switchAppMode("local")}
      >
        {m.mode_use_local()}
      </Button>
    </div>
  </div>
</div>
