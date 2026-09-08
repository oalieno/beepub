<script lang="ts">
  import { ChevronRight, Languages } from "@lucide/svelte";
  import * as m from "$lib/paraglide/messages.js";
  import { Switch } from "$lib/components/ui/switch";
  import { authStore } from "$lib/stores/auth";
  import { authApi } from "$lib/api/auth";
  import { toastStore } from "$lib/stores/toast";
  import type { ZhConversion } from "$lib/types";

  let show = $state(false);
  let saving = $state(false);

  let mode = $derived($authStore.user?.upload_zh_conversion ?? null);
  let enabled = $derived(mode !== null);
  let phrases = $derived(mode === "s2twp");

  function summary(): string {
    if (mode === "s2twp") return m.profile_zh_conversion_phrases();
    if (mode === "s2tw") return m.profile_zh_conversion_chars();
    return m.profile_zh_conversion_off();
  }

  async function save(next: ZhConversion | null) {
    if (saving || next === mode) return;
    saving = true;
    try {
      const user = await authApi.updatePreferences({
        upload_zh_conversion: next,
      });
      authStore.setUser(user);
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      saving = false;
    }
  }
</script>

<button
  class="flex items-center gap-3 px-4 py-3.5 w-full text-left hover:bg-secondary/50 transition-colors"
  onclick={() => (show = !show)}
>
  <Languages size={20} class="text-muted-foreground shrink-0" />
  <span class="text-sm font-medium flex-1">{m.profile_zh_conversion()}</span>
  <span class="text-sm text-muted-foreground">{summary()}</span>
  <ChevronRight
    size={16}
    class="text-muted-foreground/50 transition-transform {show
      ? 'rotate-90'
      : ''}"
  />
</button>
{#if show}
  <div class="px-4 pb-4 pt-1 space-y-3">
    <label class="flex items-center gap-3">
      <span class="flex-1 text-sm">{m.profile_zh_conversion_toggle()}</span>
      <Switch
        checked={enabled}
        disabled={saving}
        onCheckedChange={(on) => save(on ? "s2tw" : null)}
        aria-label={m.profile_zh_conversion_toggle()}
      />
    </label>
    <label class="flex items-center gap-3">
      <span class="flex-1 text-sm {enabled ? '' : 'text-muted-foreground'}"
        >{m.profile_zh_conversion_phrases_toggle()}</span
      >
      <Switch
        checked={phrases}
        disabled={saving || !enabled}
        onCheckedChange={(on) => save(on ? "s2twp" : "s2tw")}
        aria-label={m.profile_zh_conversion_phrases_toggle()}
      />
    </label>
    <p class="text-xs text-muted-foreground leading-relaxed">
      {m.profile_zh_conversion_hint()}
    </p>
  </div>
{/if}
