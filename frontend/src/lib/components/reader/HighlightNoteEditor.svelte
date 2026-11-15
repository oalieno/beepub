<script lang="ts">
  import ReaderDialog from "./ReaderDialog.svelte";
  import * as m from "$lib/paraglide/messages.js";

  let {
    note = "",
    text = "",
    darkMode = false,
    onsave,
    onclose,
  }: {
    note?: string;
    text?: string;
    darkMode?: boolean;
    onsave?: (note: string) => void;
    onclose?: () => void;
  } = $props();

  // svelte-ignore state_referenced_locally -- snapshot the note on open;
  // the editor is remounted per highlight, so live sync isn't wanted.
  let draft = $state(note);
  let textarea: HTMLTextAreaElement | undefined = $state();

  $effect(() => {
    textarea?.focus();
  });

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Escape") {
      e.stopPropagation();
      onclose?.();
    }
  }
</script>

<ReaderDialog
  label={m.highlight_action_note()}
  focus="own"
  {onclose}
  overlayClass="bg-black/40"
  class="max-w-[calc(100%-2rem)] sm:max-w-md rounded-2xl overflow-hidden {darkMode
    ? 'bg-ink-800 text-ink-100'
    : 'bg-card text-foreground'}"
>
  <div class="px-4 pt-4 pb-2">
    <p
      class="text-sm font-medium mb-2 {darkMode
        ? 'text-ink-300'
        : 'text-muted-foreground'}"
    >
      {m.highlight_action_note()}
    </p>
    {#if text}
      <blockquote
        class="text-xs leading-relaxed line-clamp-3 border-l-2 pl-2 mb-3 {darkMode
          ? 'border-ink-600 text-ink-400'
          : 'border-border text-muted-foreground'}"
      >
        {text}
      </blockquote>
    {/if}
    <textarea
      bind:this={textarea}
      bind:value={draft}
      rows={4}
      placeholder={m.highlight_note_placeholder()}
      class="w-full resize-none rounded-lg border p-2.5 text-sm outline-none focus:ring-2 {darkMode
        ? 'bg-ink-900 border-ink-700 text-ink-100 placeholder-ink-500 focus:ring-ink-600'
        : 'bg-background border-input text-foreground focus:ring-ring/50'}"
      onkeydown={handleKeydown}
    ></textarea>
  </div>
  <div class="flex justify-end gap-2 px-4 pb-4">
    <button
      class="rounded-lg px-4 py-2 text-sm font-medium transition-colors {darkMode
        ? 'text-ink-300 hover:bg-ink-700'
        : 'text-muted-foreground hover:bg-secondary'}"
      onclick={() => onclose?.()}
    >
      {m.common_cancel()}
    </button>
    <button
      class="rounded-lg px-4 py-2 text-sm font-medium transition-colors {darkMode
        ? 'bg-ink-100 text-ink-900 hover:bg-white'
        : 'bg-primary text-primary-foreground hover:bg-primary/90'}"
      onclick={() => onsave?.(draft.trim())}
    >
      {m.common_save()}
    </button>
  </div>
</ReaderDialog>
