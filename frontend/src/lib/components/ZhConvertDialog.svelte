<script lang="ts">
  /**
   * Convert books to Traditional Chinese — one from its page, or the
   * Simplified books of an upload (ZhUploadPrompt). A sentence of the book shows what the
   * conversion does (of several, the one picked), with the wording the
   * phrase option rewrites marked; the highlights that go along are
   * counted.
   */
  import { Button } from "$lib/components/ui/button";
  import * as Select from "$lib/components/ui/select";
  import { Switch } from "$lib/components/ui/switch";
  import Modal from "$lib/components/Modal.svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { booksApi } from "$lib/api/books";
  import {
    convertBooks,
    rememberMode,
    rememberedMode,
    type PendingBook,
  } from "$lib/services/zhConvert";
  import { toastStore } from "$lib/stores/toast";
  import type { ZhConversion, ZhConversionPreview } from "$lib/types";
  import * as m from "$lib/paraglide/messages.js";

  let {
    open,
    books,
    upload = false,
    onclose,
    onconverted,
  }: {
    open: boolean;
    books: PendingBook[];
    /** Asked after an upload, not from a book's page. */
    upload?: boolean;
    onclose: () => void;
    onconverted?: () => void;
  } = $props();

  let mode = $state<ZhConversion>("s2tw");
  let busy = $state(false);
  let previewId = $state<string | null>(null);
  let preview = $state<ZhConversionPreview | null>(null);

  $effect(() => {
    if (!open) return;
    mode = rememberedMode();
  });

  // The book previewed: the first, until another is picked.
  $effect(() => {
    if (open && !books.some((b) => b.id === previewId))
      previewId = books[0]?.id ?? null;
  });

  // The pieces carry both modes, so the switch re-renders without asking
  // again.
  $effect(() => {
    if (!open || !previewId) return;
    const id = previewId;
    preview = null;
    booksApi
      .previewZh(id)
      .then((result) => {
        if (id === previewId) preview = result;
      })
      .catch(() => {
        if (id === previewId) preview = { segments: null, highlights: 0 };
      });
  });

  // Only the wording is marked: nearly every character of a Simplified
  // book changes form, so marking those would mark everything.
  let pieces = $derived(
    (preview?.segments ?? []).map((s) => ({
      before: s.before,
      after: mode === "s2twp" ? s.phrases : s.chars,
      changed: s.before !== s.chars || s.chars !== s.phrases,
      wording: mode === "s2twp" && s.phrases !== s.chars,
    })),
  );
  let showsWording = $derived(pieces.some((p) => p.wording));
  let previewed = $derived(books.find((b) => b.id === previewId));

  let nothingToDo = $derived(!upload && preview != null && !preview.segments);

  async function convert() {
    if (busy) return;
    busy = true;
    rememberMode(mode);
    try {
      if (upload) {
        convertBooks(books, mode);
      } else {
        await booksApi.convertZh(books[0].id, mode);
        toastStore.success(m.book_convert_zh_done());
        onconverted?.();
      }
      onclose();
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      busy = false;
    }
  }
</script>

<Modal
  title={upload ? m.zh_upload_title() : m.book_convert_zh()}
  {open}
  {onclose}
>
  <div class="space-y-4 text-sm">
    {#if upload && books.length}
      <p class="text-muted-foreground">
        {books.length === 1
          ? m.zh_upload_found_one({ title: books[0].title })
          : m.zh_upload_found_many({
              title: books[0].title,
              count: String(books.length),
            })}
      </p>
    {/if}

    <label class="flex items-center gap-3">
      <span class="flex-1">
        <span class="block">{m.zh_convert_phrases()}</span>
        <span class="block text-muted-foreground text-xs mt-0.5"
          >{m.zh_convert_phrases_example()}</span
        >
      </span>
      <Switch
        checked={mode === "s2twp"}
        disabled={busy}
        onCheckedChange={(on) => (mode = on ? "s2twp" : "s2tw")}
        aria-label={m.zh_convert_phrases()}
      />
    </label>

    <div class="rounded-xl border border-border p-3 space-y-3">
      <div class="flex items-center gap-3">
        <span class="text-muted-foreground text-xs flex-1"
          >{m.zh_convert_preview()}</span
        >
        {#if books.length > 1}
          <Select.Root
            type="single"
            value={previewId ?? undefined}
            onValueChange={(v) => v && (previewId = v)}
          >
            <Select.Trigger
              class="max-w-[60%] min-w-0 h-8"
              aria-label={m.zh_convert_preview_book()}
            >
              <span class="truncate">{previewed?.title ?? ""}</span>
            </Select.Trigger>
            <Select.Content>
              {#each books as book (book.id)}
                <Select.Item value={book.id}>{book.title}</Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>
        {/if}
      </div>
      {#if !preview}
        <div class="flex justify-center py-2"><Spinner /></div>
      {:else if !preview.segments}
        <p class="text-muted-foreground">{m.zh_convert_nothing()}</p>
      {:else}
        <div>
          <span class="text-muted-foreground text-xs block"
            >{m.zh_convert_before()}</span
          >
          <p class="text-muted-foreground leading-relaxed">
            {#each pieces as piece, i (i)}<span class:opacity-60={piece.changed}
                >{piece.before}</span
              >{/each}
          </p>
        </div>
        <div>
          <span class="text-muted-foreground text-xs block"
            >{m.zh_convert_after()}</span
          >
          <p class="leading-relaxed" data-testid="zh-preview-after">
            {#each pieces as piece, i (i)}<span class:zh-mark={piece.wording}
                >{piece.after}</span
              >{/each}
          </p>
        </div>
        {#if showsWording}
          <p class="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span class="zh-mark inline-block w-3 h-3.5"></span>
            {m.zh_legend_phrases()}
          </p>
        {/if}
      {/if}
    </div>

    {#if preview && preview.highlights > 0 && !nothingToDo}
      <p>{m.zh_convert_highlights({ count: String(preview.highlights) })}</p>
    {/if}
    {#if !nothingToDo}
      <p class="text-muted-foreground">{m.zh_convert_kept()}</p>
    {/if}

    <div class="flex items-center justify-end gap-3">
      <Button variant="outline" class="rounded-xl bg-card" onclick={onclose}>
        {m.common_cancel()}
      </Button>
      <Button
        class="rounded-xl"
        disabled={busy || nothingToDo || (!upload && !preview)}
        onclick={convert}
      >
        {#if busy}<Spinner />{/if}
        {books.length > 1
          ? m.zh_convert_confirm_count({ count: String(books.length) })
          : m.zh_convert_confirm()}
      </Button>
    </div>
  </div>
</Modal>

<style>
  /* A highlighter stroke in the reader's yellow (highlight-style.ts):
     square ends, continued across a line break, underlined so it still
     reads where the fill is faint. */
  .zh-mark {
    -webkit-box-decoration-break: clone;
    box-decoration-break: clone;
    background-color: #fef08a;
    box-shadow: inset 0 -2px 0 #eab308;
  }
  :global(.dark) .zh-mark {
    background-color: rgb(254 240 138 / 0.3);
  }
</style>
