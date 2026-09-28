<script lang="ts">
  /**
   * The server is itself an OPDS catalog and a KOReader sync server; this
   * is where a reader finds the two addresses to type into an e-reader.
   */
  import { onMount } from "svelte";
  import { Check, ChevronRight, Copy, TabletSmartphone } from "@lucide/svelte";
  import { getServerUrl } from "$lib/api/client";
  import { toastStore } from "$lib/stores/toast";
  import * as m from "$lib/paraglide/messages.js";

  let expanded = $state(false);
  let copied = $state<string | null>(null);

  // The app keeps the server it connects to; the web is served by it.
  // Read in the browser: the web page is also rendered on the server.
  let origin = $state("");
  onMount(() => {
    origin = (getServerUrl() || window.location.origin).replace(/\/+$/, "");
  });
  let addresses = $derived([
    { key: "opds", label: m.profile_ereader_opds(), url: `${origin}/opds` },
    {
      key: "kosync",
      label: m.profile_ereader_kosync(),
      url: `${origin}/kosync`,
    },
  ]);

  // The clipboard API exists only on secure origins, and a home server
  // is often plain http on the LAN — there the old copy command still works.
  async function writeClipboard(text: string) {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    if (!ok) throw new Error("copy failed");
  }

  async function copy(key: string, url: string) {
    try {
      await writeClipboard(url);
      copied = key;
      setTimeout(() => {
        if (copied === key) copied = null;
      }, 2000);
    } catch {
      toastStore.error(m.profile_ereader_copy_failed());
    }
  }
</script>

<button
  class="flex items-center gap-3 px-4 py-3.5 w-full text-left hover:bg-secondary/50 transition-colors"
  onclick={() => (expanded = !expanded)}
>
  <TabletSmartphone size={20} class="text-muted-foreground shrink-0" />
  <span class="text-sm font-medium flex-1">{m.profile_ereader()}</span>
  <ChevronRight
    size={16}
    class="text-muted-foreground/50 transition-transform {expanded
      ? 'rotate-90'
      : ''}"
  />
</button>
{#if expanded && origin}
  <div class="px-4 py-4 space-y-4">
    <p class="text-xs text-muted-foreground">{m.profile_ereader_hint()}</p>
    <ul class="space-y-2">
      {#each addresses as address (address.key)}
        <li
          class="flex items-center gap-3 rounded-lg bg-secondary/40 px-3 py-2.5"
        >
          <div class="flex-1 min-w-0">
            <p class="text-xs text-muted-foreground">{address.label}</p>
            <p class="text-xs font-mono break-all select-all mt-0.5">
              {address.url}
            </p>
          </div>
          <button
            class="shrink-0 p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
            title={copied === address.key
              ? m.profile_ereader_copied()
              : m.profile_ereader_copy()}
            aria-label={m.profile_ereader_copy()}
            onclick={() => copy(address.key, address.url)}
          >
            {#if copied === address.key}
              <Check size={16} class="text-primary" />
            {:else}
              <Copy size={16} />
            {/if}
          </button>
        </li>
      {/each}
    </ul>
  </div>
{/if}
