<script lang="ts">
  import { X, Send, Trash2, Quote } from "@lucide/svelte";
  import { onMount, tick } from "svelte";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import type { CompanionMessageOut } from "$lib/types";
  import Spinner from "$lib/components/Spinner.svelte";

  let {
    bookId,
    token,
    darkMode = false,
    selectedText = null,
    selectedCfi = null,
    getCurrentCfi,
    onclose,
  }: {
    bookId: string;
    token: string;
    darkMode?: boolean;
    selectedText?: string | null;
    selectedCfi?: string | null;
    getCurrentCfi?: () => string;
    onclose?: () => void;
  } = $props();

  let messages = $state<CompanionMessageOut[]>([]);
  let inputText = $state("");
  let pendingSelectedText = $state<string | null>(null);
  let pendingCfi = $state<string | null>(null);
  let isStreaming = $state(false);
  let streamingContent = $state("");
  let loading = $state(true);
  let scrollContainer: HTMLDivElement | undefined = $state(undefined);
  let inputEl: HTMLTextAreaElement | undefined = $state(undefined);

  // Pick up selected text from highlight menu
  $effect(() => {
    if (selectedText) {
      pendingSelectedText = selectedText;
      pendingCfi = selectedCfi;
      inputEl?.focus();
    }
  });

  onMount(async () => {
    try {
      const conv = await booksApi.getCompanionConversation(bookId, token);
      if (conv?.messages) {
        messages = conv.messages;
      }
    } catch {
      // No conversation yet — that's fine
    } finally {
      loading = false;
    }
    await tick();
    scrollToBottom();
  });

  function scrollToBottom() {
    if (scrollContainer) {
      scrollContainer.scrollTop = scrollContainer.scrollHeight;
    }
  }

  async function sendMessage() {
    const text = inputText.trim();
    if (!text || isStreaming) return;

    const currentCfi = getCurrentCfi?.() || null;
    const selText = pendingSelectedText;
    const selCfi = pendingCfi;

    // Clear input immediately
    inputText = "";
    pendingSelectedText = null;
    pendingCfi = null;

    // Add user message to UI optimistically
    const userMsg: CompanionMessageOut = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      selected_text: selText,
      cfi_range: selCfi,
      created_at: new Date().toISOString(),
    };
    messages = [...messages, userMsg];
    isStreaming = true;
    streamingContent = "";

    await tick();
    scrollToBottom();

    try {
      const res = await booksApi.sendCompanionMessage(
        bookId,
        {
          message: text,
          selected_text: selText,
          cfi_range: selCfi,
          current_cfi: currentCfi,
        },
        token,
      );

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(
          (err as { detail?: string }).detail || `HTTP ${res.status}`,
        );
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response body");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("event: ")) {
            const eventType = line.slice(7).trim();
            // Next data line will follow
            continue;
          }
          if (line.startsWith("data: ")) {
            const raw = line.slice(6);
            try {
              const data = JSON.parse(raw);
              if (data.text !== undefined) {
                streamingContent += data.text;
                await tick();
                scrollToBottom();
              } else if (data.message_id) {
                // done event — add assistant message
                const assistantMsg: CompanionMessageOut = {
                  id: data.message_id,
                  role: "assistant",
                  content: streamingContent,
                  selected_text: null,
                  cfi_range: null,
                  created_at: new Date().toISOString(),
                };
                messages = [...messages, assistantMsg];
                streamingContent = "";
              } else if (data.message) {
                // error event
                toastStore.error(data.message);
              }
            } catch {
              // Not JSON, skip
            }
          }
        }
      }
    } catch (e) {
      toastStore.error((e as Error).message);
      // Remove optimistic user message on failure
      messages = messages.filter((m) => m.id !== userMsg.id);
    } finally {
      isStreaming = false;
      streamingContent = "";
    }
  }

  async function resetConversation() {
    try {
      await booksApi.deleteCompanionConversation(bookId, token);
      messages = [];
      toastStore.success("Conversation cleared");
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  function clearPendingSelection() {
    pendingSelectedText = null;
    pendingCfi = null;
  }
</script>

<!-- Backdrop -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="fixed inset-0 z-40 bg-black/20"
  onclick={() => onclose?.()}
  onkeydown={(e) => {
    if (e.key === "Escape") onclose?.();
  }}
></div>

<!-- Sidebar (right) -->
<div
  class="fixed right-0 top-0 bottom-0 z-50 w-96 max-w-[90vw] shadow-2xl flex flex-col {darkMode
    ? 'bg-gray-900 border-l border-gray-800'
    : 'bg-card border-l border-border'}"
>
  <!-- Header -->
  <div
    class="flex items-center justify-between px-4 py-3 border-b {darkMode
      ? 'border-gray-800'
      : 'border-border'}"
  >
    <p
      class="text-sm font-semibold {darkMode
        ? 'text-gray-200'
        : 'text-foreground'}"
    >
      Reading Companion
    </p>
    <div class="flex items-center gap-1">
      {#if messages.length > 0}
        <button
          class="p-1 rounded-md transition-colors {darkMode
            ? 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
            : 'text-muted-foreground hover:bg-accent hover:text-foreground'}"
          title="Clear conversation"
          onclick={resetConversation}
        >
          <Trash2 size={14} />
        </button>
      {/if}
      <button
        class="p-1 rounded-md transition-colors {darkMode
          ? 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
          : 'text-muted-foreground hover:bg-accent hover:text-foreground'}"
        onclick={() => onclose?.()}
      >
        <X size={16} />
      </button>
    </div>
  </div>

  <!-- Messages -->
  <div class="flex-1 overflow-y-auto p-4 space-y-4" bind:this={scrollContainer}>
    {#if loading}
      <div class="flex justify-center py-8">
        <Spinner size="md" class={darkMode ? "border-gray-400" : ""} />
      </div>
    {:else if messages.length === 0 && !isStreaming}
      <div
        class="flex flex-col items-center justify-center h-full text-center px-4 gap-3"
      >
        <p
          class="text-sm {darkMode ? 'text-gray-400' : 'text-muted-foreground'}"
        >
          Select text and tap the chat icon, or just ask a question about the
          book.
        </p>
      </div>
    {:else}
      {#each messages as msg (msg.id)}
        <div
          class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}"
        >
          <div
            class="max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed {msg.role ===
            'user'
              ? darkMode
                ? 'bg-blue-600 text-white'
                : 'bg-primary text-primary-foreground'
              : darkMode
                ? 'bg-gray-800 text-gray-200'
                : 'bg-muted text-foreground'}"
          >
            {#if msg.selected_text}
              <div
                class="flex items-start gap-1.5 mb-2 pb-2 border-b {msg.role ===
                'user'
                  ? darkMode
                    ? 'border-blue-500/40'
                    : 'border-primary-foreground/20'
                  : darkMode
                    ? 'border-gray-700'
                    : 'border-border'}"
              >
                <Quote size={12} class="mt-0.5 shrink-0 opacity-60" />
                <p class="text-xs opacity-80 italic line-clamp-3">
                  {msg.selected_text}
                </p>
              </div>
            {/if}
            <p class="whitespace-pre-wrap">{msg.content}</p>
          </div>
        </div>
      {/each}

      {#if isStreaming && streamingContent}
        <div class="flex justify-start">
          <div
            class="max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed {darkMode
              ? 'bg-gray-800 text-gray-200'
              : 'bg-muted text-foreground'}"
          >
            <p class="whitespace-pre-wrap">{streamingContent}</p>
          </div>
        </div>
      {/if}

      {#if isStreaming && !streamingContent}
        <div class="flex justify-start">
          <div
            class="rounded-2xl px-3.5 py-2.5 {darkMode
              ? 'bg-gray-800'
              : 'bg-muted'}"
          >
            <div class="flex gap-1">
              <span
                class="w-1.5 h-1.5 rounded-full animate-bounce {darkMode
                  ? 'bg-gray-500'
                  : 'bg-muted-foreground/40'}"
                style="animation-delay: 0ms"
              ></span>
              <span
                class="w-1.5 h-1.5 rounded-full animate-bounce {darkMode
                  ? 'bg-gray-500'
                  : 'bg-muted-foreground/40'}"
                style="animation-delay: 150ms"
              ></span>
              <span
                class="w-1.5 h-1.5 rounded-full animate-bounce {darkMode
                  ? 'bg-gray-500'
                  : 'bg-muted-foreground/40'}"
                style="animation-delay: 300ms"
              ></span>
            </div>
          </div>
        </div>
      {/if}
    {/if}
  </div>

  <!-- Input area -->
  <div class="border-t p-3 {darkMode ? 'border-gray-800' : 'border-border'}">
    {#if pendingSelectedText}
      <div
        class="flex items-start gap-2 mb-2 px-2 py-1.5 rounded-lg text-xs {darkMode
          ? 'bg-gray-800 text-gray-300'
          : 'bg-muted text-muted-foreground'}"
      >
        <Quote size={12} class="mt-0.5 shrink-0 opacity-60" />
        <p class="flex-1 line-clamp-2 italic">{pendingSelectedText}</p>
        <button
          class="shrink-0 p-0.5 rounded hover:opacity-70"
          onclick={clearPendingSelection}
        >
          <X size={12} />
        </button>
      </div>
    {/if}
    <div class="flex items-end gap-2">
      <textarea
        bind:this={inputEl}
        bind:value={inputText}
        placeholder="Ask about the book..."
        rows={1}
        class="flex-1 resize-none rounded-xl px-3.5 py-2.5 text-sm outline-none {darkMode
          ? 'bg-gray-800 text-gray-200 placeholder:text-gray-500 focus:ring-1 focus:ring-gray-600'
          : 'bg-muted text-foreground placeholder:text-muted-foreground focus:ring-1 focus:ring-ring'}"
        disabled={isStreaming}
        onkeydown={handleKeydown}
      ></textarea>
      <button
        class="shrink-0 p-2.5 rounded-xl transition-colors {isStreaming ||
        !inputText.trim()
          ? darkMode
            ? 'text-gray-600 bg-gray-800'
            : 'text-muted-foreground/40 bg-muted'
          : darkMode
            ? 'text-white bg-blue-600 hover:bg-blue-500'
            : 'text-primary-foreground bg-primary hover:bg-primary/90'}"
        disabled={isStreaming || !inputText.trim()}
        onclick={sendMessage}
      >
        <Send size={16} />
      </button>
    </div>
  </div>
</div>
