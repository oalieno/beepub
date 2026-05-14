<script lang="ts">
  import { onDestroy, tick } from "svelte";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import { sanitizeHtml } from "$lib/sanitize";
  import { marked } from "marked";
  import * as m from "$lib/paraglide/messages.js";
  import * as Tabs from "$lib/components/ui/tabs";
  import {
    NotebookPen,
    Pencil,
    Bold,
    Italic,
    Heading,
    List as ListIcon,
    Quote,
    Link as LinkIcon,
  } from "@lucide/svelte";

  type SaveState = "idle" | "saving" | "saved" | "unsaved" | "error";

  let {
    bookId,
    initialNotes = "",
    onchange,
    startEditing = $bindable(false),
  }: {
    bookId: string;
    initialNotes?: string | null;
    onchange?: (notes: string | null) => void;
    startEditing?: boolean;
  } = $props();

  let notes = $state(initialNotes ?? "");
  let editing = $state(false);
  let tab = $state<"write" | "preview">("write");
  let saveState = $state<SaveState>("idle");
  let textareaEl = $state<HTMLTextAreaElement | null>(null);
  let lastSaved = notes;
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  $effect(() => {
    if (startEditing) {
      enterEdit();
      startEditing = false;
    }
  });

  async function enterEdit() {
    editing = true;
    tab = "write";
    await tick();
    textareaEl?.focus();
  }

  function exitEdit() {
    flushSave();
    editing = false;
  }

  function scheduleSave() {
    saveState = "unsaved";
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      debounceTimer = null;
      void doSave();
    }, 800);
  }

  async function flushSave() {
    if (debounceTimer) {
      clearTimeout(debounceTimer);
      debounceTimer = null;
    }
    if (notes !== lastSaved) await doSave();
  }

  async function doSave() {
    const snapshot = notes;
    saveState = "saving";
    try {
      const value = snapshot.trim() ? snapshot : null;
      await booksApi.updateNotes(bookId, value);
      lastSaved = snapshot;
      saveState = "saved";
      onchange?.(value);
    } catch (e) {
      saveState = "error";
      toastStore.error((e as Error).message);
    }
  }

  function wrapSelection(before: string, after: string = before) {
    if (!textareaEl) return;
    const el = textareaEl;
    const start = el.selectionStart;
    const end = el.selectionEnd;
    const selected = notes.slice(start, end);
    const next =
      notes.slice(0, start) + before + selected + after + notes.slice(end);
    notes = next;
    scheduleSave();
    tick().then(() => {
      el.focus();
      const cursor = start + before.length + selected.length;
      el.setSelectionRange(cursor, cursor);
    });
  }

  function prefixLines(prefix: string) {
    if (!textareaEl) return;
    const el = textareaEl;
    const start = el.selectionStart;
    const end = el.selectionEnd;
    const lineStart = notes.lastIndexOf("\n", start - 1) + 1;
    const block = notes.slice(lineStart, end);
    const transformed = block
      .split("\n")
      .map((line) => (line.startsWith(prefix) ? line : prefix + line))
      .join("\n");
    notes = notes.slice(0, lineStart) + transformed + notes.slice(end);
    scheduleSave();
    tick().then(() => el.focus());
  }

  function insertLink() {
    if (!textareaEl) return;
    const el = textareaEl;
    const start = el.selectionStart;
    const end = el.selectionEnd;
    const selected = notes.slice(start, end) || "text";
    const snippet = `[${selected}](url)`;
    notes = notes.slice(0, start) + snippet + notes.slice(end);
    scheduleSave();
    tick().then(() => {
      el.focus();
      const urlStart = start + selected.length + 3;
      el.setSelectionRange(urlStart, urlStart + 3);
    });
  }

  onDestroy(() => {
    if (debounceTimer) {
      clearTimeout(debounceTimer);
      // best-effort fire-and-forget; the page is going away
      if (notes !== lastSaved) void doSave();
    }
  });

  const previewHtml = $derived(
    notes.trim() ? sanitizeHtml(marked.parse(notes) as string) : "",
  );

  function statusLabel(s: SaveState): string {
    if (s === "saving") return m.notes_saving();
    if (s === "saved") return m.notes_status_saved_just_now();
    if (s === "unsaved") return m.notes_status_unsaved();
    if (s === "error") return "Save failed";
    return "";
  }
</script>

<section aria-label={m.notes_title()}>
  <div class="flex items-center justify-between mb-3">
    <h2 class="text-xl font-bold text-foreground flex items-center gap-2">
      <NotebookPen size={18} />
      {m.notes_title()}
    </h2>
    {#if editing}
      <div class="flex items-center gap-3">
        <span
          class="text-xs {saveState === 'error'
            ? 'text-destructive'
            : saveState === 'unsaved'
              ? 'text-muted-foreground'
              : 'text-muted-foreground'}"
          aria-live="polite"
        >
          {statusLabel(saveState)}
        </span>
        <button
          class="text-sm font-medium text-primary hover:text-primary/80"
          onclick={exitEdit}
        >
          {m.notes_done()}
        </button>
      </div>
    {:else if notes.trim()}
      <button
        class="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
        onclick={enterEdit}
        aria-label={m.common_edit()}
      >
        <Pencil size={14} />
        {m.common_edit()}
      </button>
    {/if}
  </div>

  {#if editing}
    <div class="bg-card card-soft rounded-2xl overflow-hidden">
      <Tabs.Root
        value={tab}
        onValueChange={(v) => (tab = v as "write" | "preview")}
      >
        <div
          class="flex items-center justify-between gap-2 px-3 pt-3 pb-2 border-b border-border"
        >
          <Tabs.List class="bg-secondary/60">
            <Tabs.Trigger value="write">{m.notes_tab_write()}</Tabs.Trigger>
            <Tabs.Trigger value="preview">{m.notes_tab_preview()}</Tabs.Trigger>
          </Tabs.List>
          {#if tab === "write"}
            <div class="flex items-center gap-0.5">
              <button
                type="button"
                class="h-8 w-8 inline-flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary/60 rounded-md transition-colors"
                onclick={() => wrapSelection("**")}
                aria-label={m.notes_toolbar_bold()}
                title={m.notes_toolbar_bold()}
              >
                <Bold size={15} />
              </button>
              <button
                type="button"
                class="h-8 w-8 inline-flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary/60 rounded-md transition-colors"
                onclick={() => wrapSelection("_")}
                aria-label={m.notes_toolbar_italic()}
                title={m.notes_toolbar_italic()}
              >
                <Italic size={15} />
              </button>
              <button
                type="button"
                class="h-8 w-8 inline-flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary/60 rounded-md transition-colors"
                onclick={() => prefixLines("## ")}
                aria-label={m.notes_toolbar_heading()}
                title={m.notes_toolbar_heading()}
              >
                <Heading size={15} />
              </button>
              <button
                type="button"
                class="h-8 w-8 inline-flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary/60 rounded-md transition-colors"
                onclick={() => prefixLines("- ")}
                aria-label={m.notes_toolbar_list()}
                title={m.notes_toolbar_list()}
              >
                <ListIcon size={15} />
              </button>
              <button
                type="button"
                class="h-8 w-8 inline-flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary/60 rounded-md transition-colors"
                onclick={() => prefixLines("> ")}
                aria-label={m.notes_toolbar_quote()}
                title={m.notes_toolbar_quote()}
              >
                <Quote size={15} />
              </button>
              <button
                type="button"
                class="h-8 w-8 inline-flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-secondary/60 rounded-md transition-colors"
                onclick={insertLink}
                aria-label={m.notes_toolbar_link()}
                title={m.notes_toolbar_link()}
              >
                <LinkIcon size={15} />
              </button>
            </div>
          {/if}
        </div>

        <Tabs.Content value="write" class="m-0">
          <textarea
            bind:this={textareaEl}
            bind:value={notes}
            oninput={scheduleSave}
            onblur={flushSave}
            rows={10}
            class="w-full bg-transparent px-4 py-3 text-foreground focus:outline-none resize-y min-h-[200px] text-sm leading-relaxed"
            placeholder={m.notes_placeholder()}
          ></textarea>
        </Tabs.Content>

        <Tabs.Content value="preview" class="m-0">
          <div class="px-4 py-3 min-h-[200px]">
            {#if previewHtml}
              <div
                class="prose-description text-muted-foreground leading-relaxed"
              >
                {@html previewHtml}
              </div>
            {:else}
              <p class="text-sm text-muted-foreground italic">
                {m.notes_preview_empty()}
              </p>
            {/if}
          </div>
        </Tabs.Content>
      </Tabs.Root>
    </div>
  {:else if notes.trim()}
    <button
      type="button"
      class="block w-full text-left bg-card card-soft rounded-2xl p-4 prose-description text-muted-foreground leading-relaxed hover:bg-card/80 transition-colors cursor-text"
      onclick={enterEdit}
      aria-label={m.common_edit()}
    >
      {@html previewHtml}
    </button>
  {:else}
    <button
      type="button"
      class="w-full flex items-center gap-3 bg-card card-soft rounded-2xl p-4 text-left hover:bg-card/80 transition-colors"
      onclick={enterEdit}
    >
      <div
        class="h-10 w-10 shrink-0 rounded-full bg-primary/10 text-primary flex items-center justify-center"
      >
        <NotebookPen size={18} />
      </div>
      <div class="min-w-0">
        <p class="text-sm font-medium text-foreground">
          {m.notes_empty_title()}
        </p>
        <p class="text-xs text-muted-foreground mt-0.5 truncate">
          {m.notes_empty_subtitle()}
        </p>
      </div>
    </button>
  {/if}
</section>
