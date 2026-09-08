<script lang="ts">
  import * as m from "$lib/paraglide/messages.js";
  import { Switch } from "$lib/components/ui/switch";
  import { authStore } from "$lib/stores/auth";
  import { authApi } from "$lib/api/auth";
  import { toastStore } from "$lib/stores/toast";
  import type { ZhConversion } from "$lib/types";

  // Lives in the upload dialog, where the conversion happens: the switch is
  // the notice. Only rendered when the setting is relevant (see the dialog).
  let saving = $state(false);
  let mode = $derived($authStore.user?.upload_zh_conversion ?? null);

  async function save(next: ZhConversion | null) {
    if (saving || next === mode) return;
    saving = true;
    try {
      authStore.setUser(
        await authApi.updatePreferences({ upload_zh_conversion: next }),
      );
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      saving = false;
    }
  }
</script>

<div class="space-y-2 text-sm">
  <label class="flex items-center gap-3">
    <span class="flex-1">{m.library_upload_zh_toggle()}</span>
    <Switch
      checked={mode !== null}
      disabled={saving}
      onCheckedChange={(on) => save(on ? "s2tw" : null)}
      aria-label={m.library_upload_zh_toggle()}
    />
  </label>
  {#if mode !== null}
    <label class="flex items-center gap-3 text-muted-foreground">
      <span class="flex-1">{m.library_upload_zh_phrases()}</span>
      <Switch
        checked={mode === "s2twp"}
        disabled={saving}
        onCheckedChange={(on) => save(on ? "s2twp" : "s2tw")}
        aria-label={m.library_upload_zh_phrases()}
      />
    </label>
  {/if}
</div>
