<script lang="ts">
  /**
   * The book page's "download to this device" button (native only). Its
   * state comes from the app-wide download queue by book id, so it stays
   * true across page reuse and revisits: download → queued (tap to take
   * it back out) → progress ring → on this device.
   */
  import { Check, Download } from "@lucide/svelte";

  import { authStore } from "$lib/stores/auth";
  import {
    cancelDownloads,
    downloads,
    enqueueDownloads,
    type DownloadRequest,
  } from "$lib/stores/downloads";
  import { linkedServerBookIds } from "$lib/stores/linkedBooks";
  import { toastStore } from "$lib/stores/toast";
  import * as m from "$lib/paraglide/messages.js";

  let {
    request,
    size = "sm",
  }: { request: DownloadRequest; size?: "sm" | "lg" } = $props();

  let job = $derived($downloads.get(request.bookId));
  let percent = $derived(job?.progress ?? 0);
  // sm: the desktop action row, lg: the phone action bar.
  let box = $derived(size === "lg" ? 48 : 40);
  let r = $derived(size === "lg" ? 21 : 17);
  let dim = $derived(size === "lg" ? "h-12 w-12" : "h-10 w-10");
  let icon = $derived(size === "lg" ? 18 : 16);
</script>

{#if $linkedServerBookIds.has(request.bookId)}
  <button
    class="{dim} flex items-center justify-center bg-card card-soft rounded-full text-primary hover:shadow-md transition-all"
    onclick={() => toastStore.info(m.book_in_local_library())}
    title={m.book_in_local_library()}
  >
    <Check size={icon} />
  </button>
{:else if job}
  {@const queued = job.state === "queued"}
  <button
    class="{dim} flex items-center justify-center rounded-full relative"
    disabled={!queued}
    onclick={() => cancelDownloads([request.bookId])}
    aria-label={queued
      ? m.download_queued()
      : m.download_progress({ percent: String(percent) })}
    title={queued
      ? m.download_queued()
      : m.download_progress({ percent: String(percent) })}
    data-download-state={job.state}
  >
    <svg class="{dim} -rotate-90" viewBox="0 0 {box} {box}">
      <circle
        cx={box / 2}
        cy={box / 2}
        {r}
        fill="none"
        stroke="currentColor"
        stroke-width="2.5"
        stroke-dasharray={queued ? "3 4" : undefined}
        class={queued ? "text-muted-foreground" : "text-secondary"}
      />
      {#if !queued}
        <circle
          cx={box / 2}
          cy={box / 2}
          {r}
          fill="none"
          stroke="currentColor"
          stroke-width="2.5"
          class="text-primary"
          stroke-dasharray={2 * Math.PI * r}
          stroke-dashoffset={2 * Math.PI * r * (1 - percent / 100)}
          stroke-linecap="round"
        />
      {/if}
    </svg>
    {#if queued}
      <Download
        size={icon - 2}
        class="absolute inset-0 m-auto text-muted-foreground"
      />
    {:else}
      <span
        class="absolute inset-0 flex items-center justify-center {size === 'lg'
          ? 'text-xs'
          : 'text-[10px]'} font-semibold text-primary tabular-nums"
        >{percent}%</span
      >
    {/if}
  </button>
{:else if $authStore.user?.can_download}
  <button
    aria-label={m.book_download_to_library()}
    class="{dim} flex items-center justify-center bg-card card-soft rounded-full text-foreground hover:shadow-md transition-all"
    onclick={() => enqueueDownloads([request])}
    title={m.book_download_to_library()}
  >
    <Download size={icon} />
  </button>
{/if}
