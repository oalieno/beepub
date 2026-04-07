<script lang="ts">
  import html2canvas from "html2canvas";
  import { X, Download, Share2, LoaderCircle } from "@lucide/svelte";
  import ShareHighlightCard from "./ShareHighlightCard.svelte";
  import type { HighlightOut } from "$lib/types";
  import * as m from "$lib/paraglide/messages.js";

  let {
    open = false,
    highlight = null as HighlightOut | null,
    bookTitle = "",
    bookAuthors = [] as string[],
    onclose,
  }: {
    open?: boolean;
    highlight?: HighlightOut | null;
    bookTitle?: string;
    bookAuthors?: string[];
    onclose?: () => void;
  } = $props();

  let cardContainer: HTMLDivElement | undefined = $state();
  let previewWrapper: HTMLDivElement | undefined = $state();
  let previewScale = $state(0.3);
  let downloading = $state(false);
  let sharing = $state(false);

  $effect(() => {
    if (previewWrapper && open) {
      const updateScale = () => {
        if (previewWrapper) {
          previewScale = previewWrapper.clientWidth / 1080;
        }
      };
      updateScale();
      const observer = new ResizeObserver(updateScale);
      observer.observe(previewWrapper);
      return () => observer.disconnect();
    }
  });

  function close() {
    onclose?.();
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Escape") close();
  }

  async function captureCard(): Promise<Blob | null> {
    if (!cardContainer) return null;
    const cardEl = cardContainer.querySelector(".share-card") as HTMLElement;
    if (!cardEl) return null;

    // Clone the card to an off-screen container at full size (no CSS transform)
    const clone = cardEl.cloneNode(true) as HTMLElement;
    clone.style.position = "fixed";
    clone.style.left = "-9999px";
    clone.style.top = "0";
    clone.style.transform = "none";
    clone.style.zIndex = "-1";
    document.body.appendChild(clone);

    await document.fonts.ready;

    try {
      const canvas = await html2canvas(clone, {
        scale: 1,
        useCORS: true,
        backgroundColor: "#faf7f2",
        width: 1080,
        height: 1350,
      });

      return new Promise((resolve) => {
        canvas.toBlob((blob) => resolve(blob), "image/png", 1.0);
      });
    } finally {
      document.body.removeChild(clone);
    }
  }

  async function handleDownload() {
    downloading = true;
    try {
      const blob = await captureCard();
      if (!blob) return;

      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `highlight-${highlight?.id?.slice(0, 8) ?? "card"}.png`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } finally {
      downloading = false;
    }
  }

  async function handleShare() {
    sharing = true;
    try {
      const blob = await captureCard();
      if (!blob) return;

      const file = new File([blob], "highlight.png", { type: "image/png" });

      if (navigator.share && navigator.canShare?.({ files: [file] })) {
        await navigator.share({ files: [file] });
      } else {
        await handleDownload();
      }
    } finally {
      sharing = false;
    }
  }

  let canShare = $derived(
    typeof navigator !== "undefined" && !!navigator.share,
  );
</script>

<svelte:window onkeydown={handleKeydown} />

{#if open && highlight}
  <div
    class="fixed inset-0 z-50 flex items-center justify-center p-4"
    role="dialog"
    aria-modal="true"
  >
    <button
      class="absolute inset-0 bg-black/40 backdrop-blur-sm"
      aria-label={m.common_close()}
      onclick={close}
    ></button>

    <div
      class="relative bg-card rounded-2xl shadow-2xl flex flex-col"
      style="max-height: 90vh; width: min(calc((90vh - 120px) * 4 / 5 + 40px), 560px);"
      role="document"
    >
      <!-- Header -->
      <div class="flex items-center justify-between px-5 py-3 flex-shrink-0">
        <h2 class="text-base font-bold text-foreground">
          {m.share_highlight_title()}
        </h2>
        <button
          class="w-8 h-8 rounded-full bg-secondary flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary/80 transition-colors"
          onclick={close}
          aria-label={m.common_close()}
        >
          <X size={16} />
        </button>
      </div>

      <!-- Card preview (scaled down) -->
      <div class="px-5 pb-3 overflow-hidden min-h-0 flex-1">
        <div
          bind:this={previewWrapper}
          class="rounded-xl overflow-hidden shadow-lg relative h-full"
          style="aspect-ratio: 4/5;"
        >
          <div
            bind:this={cardContainer}
            style="
              width: 1080px;
              height: 1350px;
              transform-origin: top left;
              transform: scale({previewScale});
              position: absolute;
              top: 0;
              left: 0;
            "
          >
            <ShareHighlightCard
              text={highlight.text}
              {bookTitle}
              authors={bookAuthors}
              note={highlight.note}
            />
          </div>
        </div>
      </div>

      <!-- Action buttons -->
      <div class="px-5 pb-4 pt-1 flex gap-3 flex-shrink-0">
        <button
          class="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-secondary text-secondary-foreground hover:bg-secondary/80 transition-colors text-sm font-medium disabled:opacity-50"
          onclick={handleDownload}
          disabled={downloading || sharing}
        >
          {#if downloading}
            <LoaderCircle size={16} class="animate-spin" />
          {:else}
            <Download size={16} />
          {/if}
          {m.common_save()}
        </button>
        {#if canShare}
          <button
            class="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 transition-colors text-sm font-medium disabled:opacity-50"
            onclick={handleShare}
            disabled={downloading || sharing}
          >
            {#if sharing}
              <LoaderCircle size={16} class="animate-spin" />
            {:else}
              <Share2 size={16} />
            {/if}
            {m.common_share()}
          </button>
        {/if}
      </div>
    </div>
  </div>
{/if}
