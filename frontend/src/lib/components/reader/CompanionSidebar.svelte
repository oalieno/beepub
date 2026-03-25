<script lang="ts">
  import {
    X,
    ArrowUp,
    Trash2,
    Quote,
    MessageCircle,
    Settings,
    Plus,
    History,
    Pencil,
    Check,
  } from "@lucide/svelte";
  import { onMount, tick } from "svelte";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import type {
    AiStatus,
    CompanionConversationSummary,
    CompanionMessageOut,
  } from "$lib/types";
  import Spinner from "$lib/components/Spinner.svelte";

  let {
    bookId,
    darkMode = false,
    aiStatus = { companion: false, tag: false, image: false, embedding: false },
    isAdmin = false,
    selectedText = null,
    selectedCfi = null,
    getCurrentCfi,
    onclose,
  }: {
    bookId: string;
    darkMode?: boolean;
    aiStatus?: AiStatus;
    isAdmin?: boolean;
    selectedText?: string | null;
    selectedCfi?: string | null;
    getCurrentCfi?: () => string;
    onclose?: () => void;
  } = $props();

  // Session list state
  let conversations = $state<CompanionConversationSummary[]>([]);
  let activeConversationId = $state<string | null>(null);
  let showSessionList = $state(false);
  let loadingList = $state(true);

  // Chat state
  let messages = $state<CompanionMessageOut[]>([]);
  let inputText = $state("");
  let pendingSelectedText = $state<string | null>(null);
  let pendingCfi = $state<string | null>(null);
  let isStreaming = $state(false);
  let streamingContent = $state("");
  let loading = $state(false);
  let scrollContainer: HTMLDivElement | undefined = $state(undefined);
  let inputEl: HTMLTextAreaElement | undefined = $state(undefined);

  // Rename state
  let renamingId = $state<string | null>(null);
  let renameValue = $state("");

  // Pick up selected text from highlight menu
  $effect(() => {
    if (selectedText) {
      pendingSelectedText = selectedText;
      pendingCfi = selectedCfi;
      // If on session list, switch to chat
      showSessionList = false;
      inputEl?.focus();
    }
  });

  onMount(async () => {
    await loadConversationList();
  });

  async function loadConversationList() {
    loadingList = true;
    try {
      conversations = await booksApi.listCompanionConversations(bookId);
      // Auto-open the most recent conversation, or show list if multiple
      if (conversations.length === 1) {
        await selectConversation(conversations[0].id);
      } else if (conversations.length > 1) {
        showSessionList = true;
      }
      // If 0 conversations, show empty chat (will create on first message)
    } catch {
      // ignore
    } finally {
      loadingList = false;
    }
  }

  async function selectConversation(convId: string) {
    activeConversationId = convId;
    showSessionList = false;
    loading = true;
    messages = [];
    try {
      const conv = await booksApi.getCompanionConversation(bookId, convId);
      messages = conv.messages;
    } catch {
      toastStore.error("Failed to load conversation");
    } finally {
      loading = false;
    }
    await tick();
    scrollToBottom();
    inputEl?.focus();
  }

  function startNewConversation() {
    activeConversationId = null;
    messages = [];
    showSessionList = false;
    inputEl?.focus();
  }

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
      const res = await booksApi.sendCompanionMessage(bookId, {
        message: text,
        selected_text: selText,
        cfi_range: selCfi,
        current_cfi: currentCfi,
        conversation_id: activeConversationId,
      });

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
                // done event — capture conversation_id for new conversations
                if (!activeConversationId && data.conversation_id) {
                  activeConversationId = data.conversation_id;
                  // Refresh the conversation list
                  booksApi
                    .listCompanionConversations(bookId)
                    .then((c) => (conversations = c))
                    .catch(() => {});
                }
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
      messages = messages.filter((m) => m.id !== userMsg.id);
    } finally {
      isStreaming = false;
      streamingContent = "";
    }
  }

  async function deleteConversation(convId: string) {
    try {
      await booksApi.deleteCompanionConversation(bookId, convId);
      conversations = conversations.filter((c) => c.id !== convId);
      if (activeConversationId === convId) {
        activeConversationId = null;
        messages = [];
        if (conversations.length > 0) {
          showSessionList = true;
        }
      }
      toastStore.success("Conversation deleted");
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  function startRename(conv: CompanionConversationSummary) {
    renamingId = conv.id;
    renameValue = conv.title || "";
  }

  async function confirmRename() {
    if (!renamingId) return;
    const title = renameValue.trim();
    if (!title) {
      renamingId = null;
      return;
    }
    try {
      await booksApi.renameCompanionConversation(bookId, renamingId, title);
      conversations = conversations.map((c) =>
        c.id === renamingId ? { ...c, title } : c,
      );
    } catch (e) {
      toastStore.error((e as Error).message);
    }
    renamingId = null;
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

  function conversationLabel(conv: CompanionConversationSummary): string {
    if (conv.title) return conv.title;
    const d = new Date(conv.created_at);
    return d.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  let activeTitle = $derived(
    conversations.find((c) => c.id === activeConversationId)?.title || null,
  );
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
  class="fixed right-0 top-0 bottom-0 z-50 w-[28rem] max-w-[90vw] shadow-2xl flex flex-col {darkMode
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
      class="text-sm font-semibold truncate {darkMode
        ? 'text-gray-200'
        : 'text-foreground'}"
    >
      {#if showSessionList}
        Conversations
      {:else if activeTitle}
        {activeTitle}
      {:else}
        Reading Companion
      {/if}
    </p>
    <div class="flex items-center gap-1">
      {#if !showSessionList}
        <button
          class="p-1 rounded-md transition-colors {darkMode
            ? 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
            : 'text-muted-foreground hover:bg-accent hover:text-foreground'}"
          title="New conversation"
          onclick={startNewConversation}
        >
          <Plus size={16} />
        </button>
        <button
          class="p-1 rounded-md transition-colors {darkMode
            ? 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
            : 'text-muted-foreground hover:bg-accent hover:text-foreground'}"
          title="Past conversations"
          onclick={() => (showSessionList = true)}
        >
          <History size={16} />
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

  {#if !aiStatus.companion}
    <!-- Not configured overlay -->
    <div
      class="flex-1 flex flex-col items-center justify-center px-6 text-center gap-4"
    >
      <div
        class="w-12 h-12 rounded-full flex items-center justify-center {darkMode
          ? 'bg-gray-800'
          : 'bg-muted'}"
      >
        <MessageCircle
          size={24}
          class={darkMode ? "text-gray-500" : "text-muted-foreground/50"}
        />
      </div>
      <div class="space-y-2">
        <p
          class="text-sm font-medium {darkMode
            ? 'text-gray-300'
            : 'text-foreground'}"
        >
          Companion AI not configured
        </p>
        {#if isAdmin}
          <p
            class="text-xs {darkMode
              ? 'text-gray-500'
              : 'text-muted-foreground'}"
          >
            Set up a provider and model in admin settings.
          </p>
          <a
            href="/admin/settings"
            class="inline-flex items-center gap-1.5 text-xs font-medium mt-1 {darkMode
              ? 'text-blue-400 hover:text-blue-300'
              : 'text-primary hover:text-primary/80'}"
          >
            <Settings size={12} />
            Go to Settings
          </a>
        {:else}
          <p
            class="text-xs {darkMode
              ? 'text-gray-500'
              : 'text-muted-foreground'}"
          >
            Ask your admin to enable AI features in the settings.
          </p>
        {/if}
      </div>
    </div>
  {:else if loadingList}
    <div class="flex-1 flex justify-center items-center py-8">
      <Spinner size="md" class={darkMode ? "border-gray-400" : ""} />
    </div>
  {:else if showSessionList}
    <!-- Session list -->
    <div class="flex-1 overflow-y-auto p-2">
      {#if conversations.length === 0}
        <div
          class="flex flex-col items-center justify-center h-full text-center px-4 gap-3"
        >
          <p
            class="text-sm {darkMode
              ? 'text-gray-400'
              : 'text-muted-foreground'}"
          >
            No conversations yet. Start a new one!
          </p>
          <button
            class="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg transition-colors {darkMode
              ? 'bg-gray-800 text-gray-300 hover:bg-gray-700'
              : 'bg-muted text-foreground hover:bg-accent'}"
            onclick={startNewConversation}
          >
            <Plus size={14} />
            New conversation
          </button>
        </div>
      {:else}
        <div class="flex flex-col gap-1">
          {#each conversations as conv (conv.id)}
            <div
              class="group flex items-center gap-1 rounded-lg transition-colors {darkMode
                ? 'hover:bg-gray-800'
                : 'hover:bg-accent'}"
            >
              {#if renamingId === conv.id}
                <div class="flex-1 flex items-center gap-1 px-3 py-2">
                  <input
                    bind:value={renameValue}
                    class="flex-1 text-sm px-1.5 py-0.5 rounded outline-none {darkMode
                      ? 'bg-gray-700 text-gray-200'
                      : 'bg-muted text-foreground'}"
                    onkeydown={(e) => {
                      if (e.key === "Enter") confirmRename();
                      if (e.key === "Escape") renamingId = null;
                    }}
                  />
                  <button
                    class="p-1 rounded-md {darkMode
                      ? 'text-gray-400 hover:text-gray-200'
                      : 'text-muted-foreground hover:text-foreground'}"
                    onclick={confirmRename}
                  >
                    <Check size={14} />
                  </button>
                </div>
              {:else}
                <button
                  class="flex-1 text-left px-3 py-2 min-w-0"
                  onclick={() => selectConversation(conv.id)}
                >
                  <p
                    class="text-sm truncate {darkMode
                      ? 'text-gray-200'
                      : 'text-foreground'}"
                  >
                    {conversationLabel(conv)}
                  </p>
                  <p
                    class="text-xs {darkMode
                      ? 'text-gray-500'
                      : 'text-muted-foreground'}"
                  >
                    {new Date(conv.updated_at).toLocaleDateString()}
                  </p>
                </button>
                <div
                  class="flex items-center gap-0.5 pr-2 opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <button
                    class="p-1 rounded-md {darkMode
                      ? 'text-gray-400 hover:text-gray-200 hover:bg-gray-700'
                      : 'text-muted-foreground hover:text-foreground hover:bg-muted'}"
                    title="Rename"
                    onclick={() => startRename(conv)}
                  >
                    <Pencil size={12} />
                  </button>
                  <button
                    class="p-1 rounded-md {darkMode
                      ? 'text-gray-400 hover:text-red-400 hover:bg-gray-700'
                      : 'text-muted-foreground hover:text-red-500 hover:bg-muted'}"
                    title="Delete"
                    onclick={() => deleteConversation(conv.id)}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              {/if}
            </div>
          {/each}
        </div>
      {/if}
    </div>
  {:else}
    <!-- Chat view -->
    <!-- Messages -->
    <div
      class="flex-1 overflow-y-auto p-4 space-y-4"
      bind:this={scrollContainer}
    >
      {#if loading}
        <div class="flex justify-center py-8">
          <Spinner size="md" class={darkMode ? "border-gray-400" : ""} />
        </div>
      {:else if messages.length === 0 && !isStreaming}
        <div
          class="flex flex-col items-center justify-center h-full text-center px-4 gap-3"
        >
          <p
            class="text-sm {darkMode
              ? 'text-gray-400'
              : 'text-muted-foreground'}"
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

    <!-- Input area — unified container -->
    <div class="p-3">
      <div
        class="rounded-2xl border transition-colors {darkMode
          ? 'border-gray-700 bg-gray-800/50 focus-within:border-gray-600'
          : 'border-border bg-muted/50 focus-within:border-ring'}"
      >
        {#if pendingSelectedText}
          <div
            class="flex items-start gap-2 mx-3 mt-2.5 px-2.5 py-1.5 rounded-lg text-xs {darkMode
              ? 'bg-gray-700/60 text-gray-300'
              : 'bg-background text-muted-foreground'}"
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
        <textarea
          bind:this={inputEl}
          bind:value={inputText}
          placeholder="Ask about the book..."
          rows={1}
          class="w-full resize-none bg-transparent px-3.5 py-2.5 text-sm outline-none overflow-hidden {darkMode
            ? 'text-gray-200 placeholder:text-gray-500'
            : 'text-foreground placeholder:text-muted-foreground'}"
          style="max-height: 120px; overflow-y: {inputText.split('\n').length >
          4
            ? 'auto'
            : 'hidden'}"
          disabled={isStreaming}
          onkeydown={handleKeydown}
          oninput={(e) => {
            const el = e.currentTarget;
            el.style.height = "auto";
            el.style.height = Math.min(el.scrollHeight, 120) + "px";
          }}
        ></textarea>
        <div class="flex items-center justify-end px-2.5 pb-2">
          <button
            class="w-7 h-7 flex items-center justify-center rounded-full transition-colors {isStreaming ||
            !inputText.trim()
              ? darkMode
                ? 'text-gray-600 bg-gray-700'
                : 'text-muted-foreground/30 bg-muted'
              : darkMode
                ? 'text-white bg-blue-600 hover:bg-blue-500'
                : 'text-primary-foreground bg-primary hover:bg-primary/90'}"
            disabled={isStreaming || !inputText.trim()}
            onclick={sendMessage}
          >
            <ArrowUp size={16} strokeWidth={2.5} />
          </button>
        </div>
      </div>
    </div>
  {/if}
</div>
