<script lang="ts">
  import { WifiOff } from "@lucide/svelte";
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
      // On success isOnline flips and the shell dissolves by itself.
    } finally {
      checking = false;
    }
  }
</script>

<div
  role="status"
  class="bg-muted/50 border border-border rounded-2xl px-5 py-4 flex items-center gap-3"
>
  <WifiOff class="text-muted-foreground shrink-0" size={20} />
  <p class="text-sm text-foreground flex-1">
    {m.home_offline_message()}
  </p>
  <Button
    variant="outline"
    size="sm"
    class="shrink-0 rounded-xl"
    disabled={checking}
    onclick={retry}
  >
    {checking ? m.home_offline_checking() : m.home_offline_retry()}
  </Button>
</div>
