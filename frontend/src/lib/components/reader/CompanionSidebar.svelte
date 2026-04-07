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
    ArrowLeft,
  } from "@lucide/svelte";
  import { onMount, onDestroy, tick } from "svelte";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import type {
    AiStatus,
    CompanionConversationSummary,
    CompanionMessageOut,
  } from "$lib/types";
  import Spinner from "$lib/components/Spinner.svelte";
  import * as m from "$lib/paraglide/messages.js";

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

  const suggestedPrompts = $derived([
    m.companion_prompt_summarize(),
    m.companion_prompt_themes(),
    m.companion_prompt_characters(),
  ]);

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

  // Animation state
  let visible = $state(false);
  let backdropVisible = $state(false);

  // Swipe state
  let swipingId = $state<string | null>(null);
  let swipeX = $state(0);
  let touchStartX = 0;
  let touchStartY = 0;
  let isSwiping = false;

  // Pending delete (for undo)
  let pendingDeleteId = $state<string | null>(null);
  let pendingDeleteTimer: ReturnType<typeof setTimeout> | null = null;

  // Cleanup tracking
  let destroyed = false;
  let closeTimer: ReturnType<typeof setTimeout> | null = null;
  let focusTimer: ReturnType<typeof setTimeout> | null = null;
  let activeReader: ReadableStreamDefaultReader | null = null;

  // Detect mobile
  const isMobile = typeof window !== "undefined" && window.innerWidth < 640;

  // Pick up selected text from highlight menu (only on initial mount or when selection changes)
  let lastSelectedText: string | null = null;
  $effect(() => {
    if (selectedText && selectedText !== lastSelectedText) {
      lastSelectedText = selectedText;
      pendingSelectedText = selectedText;
      pendingCfi = selectedCfi;
      showSessionList = false;
      inputEl?.focus();
    }
  });

  onMount(async () => {
    // Trigger enter animation
    backdropVisible = true;
    requestAnimationFrame(() => {
      visible = true;
    });

    await loadConversationList();

    // Focus input on desktop after animation
    if (!isMobile) {
      const FOCUS_DELAY_MS = 220;
      focusTimer = setTimeout(() => inputEl?.focus(), FOCUS_DELAY_MS);
    }
  });

  onDestroy(() => {
    destroyed = true;
    if (closeTimer) clearTimeout(closeTimer);
    if (focusTimer) clearTimeout(focusTimer);
    if (pendingDeleteTimer) clearTimeout(pendingDeleteTimer);
    activeReader?.cancel().catch(() => {});
  });

  function close() {
    visible = false;
    backdropVisible = false;
    closeTimer = setTimeout(() => onclose?.(), 200);
  }

  async function loadConversationList() {
    loadingList = true;
    try {
      conversations = await booksApi.listCompanionConversations(bookId);
    } catch {
      toastStore.error(m.companion_failed_load_list());
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
      toastStore.error(m.companion_failed_load());
    } finally {
      loading = false;
    }
    await tick();
    scrollToBottom();
    if (!isMobile) inputEl?.focus();
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

    inputText = "";
    pendingSelectedText = null;
    pendingCfi = null;

    // Reset textarea height
    if (inputEl) {
      inputEl.style.height = "auto";
    }

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
      activeReader = reader;

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done || destroyed) break;

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
                if (!activeConversationId && data.conversation_id) {
                  activeConversationId = data.conversation_id;
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
      messages = messages.filter((msg) => msg.id !== userMsg.id);
    } finally {
      activeReader = null;
      isStreaming = false;
      streamingContent = "";
    }
  }

  function deleteConversation(convId: string) {
    // Optimistically hide from UI
    pendingDeleteId = convId;

    // Clear any existing timer
    if (pendingDeleteTimer) clearTimeout(pendingDeleteTimer);

    toastStore.info(m.companion_deleted(), {
      action: {
        label: m.common_undo(),
        onclick: () => {
          if (pendingDeleteTimer) clearTimeout(pendingDeleteTimer);
          pendingDeleteId = null;
          pendingDeleteTimer = null;
        },
      },
      duration: 5000,
    });

    pendingDeleteTimer = setTimeout(async () => {
      try {
        await booksApi.deleteCompanionConversation(bookId, convId);
        conversations = conversations.filter((c) => c.id !== convId);
        if (activeConversationId === convId) {
          activeConversationId = null;
          messages = [];
          if (conversations.filter((c) => c.id !== convId).length > 0) {
            showSessionList = true;
          }
        }
      } catch (e) {
        toastStore.error((e as Error).message);
      }
      pendingDeleteId = null;
      pendingDeleteTimer = null;
    }, 5000);
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
    return d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  // Swipe handlers
  function handleTouchStart(e: TouchEvent, convId: string) {
    touchStartX = e.touches[0].clientX;
    touchStartY = e.touches[0].clientY;
    isSwiping = false;
    swipingId = convId;
    swipeX = 0;
  }

  function handleTouchMove(e: TouchEvent) {
    if (!swipingId) return;
    const dx = e.touches[0].clientX - touchStartX;
    const dy = e.touches[0].clientY - touchStartY;

    // Determine if swiping horizontally
    if (!isSwiping && Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 10) {
      isSwiping = true;
    }

    if (isSwiping) {
      e.preventDefault();
      swipeX = Math.min(0, dx); // Only allow left swipe
    }
  }

  function handleTouchEnd() {
    if (!swipingId) return;
    if (swipeX < -80) {
      // Threshold reached — delete
      deleteConversation(swipingId);
    }
    swipeX = 0;
    swipingId = null;
    isSwiping = false;
  }

  let activeTitle = $derived(
    conversations.find((c) => c.id === activeConversationId)?.title || null,
  );

  let visibleConversations = $derived(
    conversations.filter((c) => c.id !== pendingDeleteId),
  );
</script>

<!-- Backdrop -->
<div
  class="fixed inset-0 z-40 bg-black/20 transition-opacity duration-200 {backdropVisible
    ? 'opacity-100'
    : 'opacity-0'}"
  role="presentation"
  onclick={() => close()}
  onkeydown={(e) => {
    if (e.key === "Escape") close();
  }}
></div>

<!-- Sidebar / Full-screen sheet -->
<div
  class="fixed z-50 flex flex-col touch-manipulation
    inset-0 sm:inset-auto sm:right-0 sm:top-0 sm:bottom-0 sm:w-[28rem]
    shadow-2xl transition-transform duration-200 ease-out
    {visible ? 'translate-x-0' : 'translate-x-full'}
    {darkMode
    ? 'bg-gray-900 sm:border-l sm:border-gray-800'
    : 'bg-card sm:border-l sm:border-border'}"
  style="padding-top: env(safe-area-inset-top, 0px);"
  role="dialog"
  aria-modal="true"
  aria-label={m.companion_title()}
>
  <!-- Header -->
  <div
    class="flex items-center justify-between px-3 sm:px-4 py-3 border-b {darkMode
      ? 'border-gray-800'
      : 'border-border'}"
  >
    <!-- Left: back/close on mobile, title on desktop -->
    <div class="flex items-center gap-1 min-w-0 flex-1">
      {#if showSessionList}
        <!-- Session list: back to chat -->
        <button
          class="p-2 -ml-1 rounded-lg transition-colors {darkMode
            ? 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
            : 'text-muted-foreground hover:bg-accent hover:text-foreground'}"
          aria-label={m.companion_back_to_chat()}
          onclick={() => (showSessionList = false)}
        >
          <ArrowLeft size={20} />
        </button>
        <p
          class="text-base font-semibold truncate {darkMode
            ? 'text-gray-200'
            : 'text-foreground'}"
        >
          {m.companion_conversations()}
        </p>
      {:else}
        <!-- Chat view -->
        <button
          class="p-2 -ml-1 rounded-lg sm:hidden transition-colors {darkMode
            ? 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
            : 'text-muted-foreground hover:bg-accent hover:text-foreground'}"
          aria-label={m.common_close()}
          onclick={() => close()}
        >
          <ArrowLeft size={20} />
        </button>
        <p
          class="text-base font-semibold truncate {darkMode
            ? 'text-gray-200'
            : 'text-foreground'}"
        >
          {#if activeTitle}
            {activeTitle}
          {:else}
            {m.companion_title()}
          {/if}
        </p>
      {/if}
    </div>

    <!-- Right: actions -->
    <div class="flex items-center gap-0.5">
      {#if showSessionList}
        <!-- Session list: new conversation -->
        <button
          class="p-2 rounded-lg transition-colors {darkMode
            ? 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
            : 'text-muted-foreground hover:bg-accent hover:text-foreground'}"
          aria-label={m.companion_new_conv()}
          onclick={startNewConversation}
        >
          <Plus size={20} />
        </button>
      {:else}
        <!-- Chat view: icon buttons -->
        <div class="flex items-center gap-0.5">
          <button
            class="p-2 rounded-lg transition-colors {darkMode
              ? 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
              : 'text-muted-foreground hover:bg-accent hover:text-foreground'}"
            aria-label={m.companion_new_conv()}
            onclick={startNewConversation}
          >
            <Plus size={18} />
          </button>
          <button
            class="p-2 rounded-lg transition-colors {darkMode
              ? 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
              : 'text-muted-foreground hover:bg-accent hover:text-foreground'}"
            aria-label={m.companion_past_conv()}
            onclick={() => (showSessionList = true)}
          >
            <History size={18} />
          </button>
        </div>
      {/if}

      <!-- Close button (desktop only, mobile uses back arrow) -->
      <button
        class="hidden sm:flex p-2 rounded-lg transition-colors {darkMode
          ? 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
          : 'text-muted-foreground hover:bg-accent hover:text-foreground'}"
        aria-label={m.common_close()}
        onclick={() => close()}
      >
        <X size={18} />
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
          class="text-base font-medium {darkMode
            ? 'text-gray-300'
            : 'text-foreground'}"
        >
          {m.companion_not_configured()}
        </p>
        {#if isAdmin}
          <p
            class="text-sm {darkMode
              ? 'text-gray-500'
              : 'text-muted-foreground'}"
          >
            {m.companion_admin_setup()}
          </p>
          <a
            href="/admin/settings"
            class="inline-flex items-center gap-1.5 text-sm font-medium mt-1 {darkMode
              ? 'text-blue-400 hover:text-blue-300'
              : 'text-primary hover:text-primary/80'}"
          >
            <Settings size={14} />
            {m.companion_go_to_settings()}
          </a>
        {:else}
          <p
            class="text-sm {darkMode
              ? 'text-gray-500'
              : 'text-muted-foreground'}"
          >
            {m.companion_user_msg()}
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
      {#if visibleConversations.length === 0}
        <div
          class="flex flex-col items-center justify-center h-full text-center px-4 gap-3"
        >
          <p
            class="text-base {darkMode
              ? 'text-gray-400'
              : 'text-muted-foreground'}"
          >
            {m.companion_no_conversations()}
          </p>
          <button
            class="inline-flex items-center gap-1.5 px-4 py-2.5 text-base rounded-lg transition-colors {darkMode
              ? 'bg-gray-800 text-gray-300 hover:bg-gray-700'
              : 'bg-muted text-foreground hover:bg-accent'}"
            onclick={startNewConversation}
          >
            <Plus size={16} />
            {m.companion_new_conv()}
          </button>
        </div>
      {:else}
        <div class="flex flex-col gap-1">
          {#each visibleConversations as conv (conv.id)}
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <div
              class="relative overflow-hidden rounded-lg"
              ontouchstart={(e) => handleTouchStart(e, conv.id)}
              ontouchmove={(e) => handleTouchMove(e)}
              ontouchend={() => handleTouchEnd()}
            >
              <!-- Delete zone (revealed by swipe) -->
              <div
                class="absolute inset-y-0 right-0 w-20 flex items-center justify-center bg-red-500 text-white"
              >
                <Trash2 size={18} />
              </div>

              <!-- Conversation item -->
              <div
                class="relative flex items-center gap-1 transition-colors {darkMode
                  ? 'bg-gray-900 hover:bg-gray-800'
                  : 'bg-card hover:bg-accent'}"
                style={swipingId === conv.id
                  ? `transform: translateX(${swipeX}px)`
                  : ""}
              >
                {#if renamingId === conv.id}
                  <div class="flex-1 flex items-center gap-1 px-3 py-3">
                    <input
                      bind:value={renameValue}
                      class="flex-1 text-base px-2 py-1 rounded outline-none {darkMode
                        ? 'bg-gray-700 text-gray-200'
                        : 'bg-muted text-foreground'}"
                      onkeydown={(e) => {
                        if (e.key === "Enter") confirmRename();
                        if (e.key === "Escape") renamingId = null;
                      }}
                    />
                    <button
                      class="p-2 rounded-lg {darkMode
                        ? 'text-gray-400 hover:text-gray-200'
                        : 'text-muted-foreground hover:text-foreground'}"
                      aria-label={m.companion_confirm_rename()}
                      onclick={confirmRename}
                    >
                      <Check size={16} />
                    </button>
                  </div>
                {:else}
                  <button
                    class="flex-1 text-left px-3 py-3 min-w-0"
                    onclick={() => selectConversation(conv.id)}
                  >
                    <p
                      class="text-base truncate {darkMode
                        ? 'text-gray-200'
                        : 'text-foreground'}"
                    >
                      {conversationLabel(conv)}
                    </p>
                    <p
                      class="text-xs mt-0.5 {darkMode
                        ? 'text-gray-500'
                        : 'text-muted-foreground'}"
                    >
                      {new Date(conv.updated_at).toLocaleDateString()}
                    </p>
                  </button>
                  <!-- Always-visible actions -->
                  <div class="flex items-center gap-0.5 pr-2">
                    <button
                      class="p-2 rounded-lg opacity-60 hover:opacity-100 transition-opacity {darkMode
                        ? 'text-gray-400 hover:bg-gray-700'
                        : 'text-muted-foreground hover:bg-muted'}"
                      aria-label={m.companion_rename()}
                      onclick={() => startRename(conv)}
                    >
                      <Pencil size={14} />
                    </button>
                    <button
                      class="p-2 rounded-lg opacity-60 hover:opacity-100 transition-opacity {darkMode
                        ? 'text-gray-400 hover:text-red-400 hover:bg-gray-700'
                        : 'text-muted-foreground hover:text-red-500 hover:bg-muted'}"
                      aria-label={m.companion_delete()}
                      onclick={() => deleteConversation(conv.id)}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                {/if}
              </div>
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
        <!-- Empty state with suggested prompts -->
        <div
          class="flex flex-col items-center justify-center h-full text-center px-4 gap-5"
        >
          <div
            class="w-14 h-14 rounded-full flex items-center justify-center {darkMode
              ? 'bg-gray-800'
              : 'bg-muted'}"
          >
            <MessageCircle
              size={28}
              class={darkMode ? "text-gray-500" : "text-muted-foreground/40"}
            />
          </div>
          <p
            class="text-base {darkMode
              ? 'text-gray-400'
              : 'text-muted-foreground'}"
          >
            {m.companion_empty_prompt()}
          </p>
          <div class="flex flex-col gap-2 w-full max-w-[18rem]">
            {#each suggestedPrompts as prompt}
              <button
                class="text-left px-4 py-3 rounded-xl border text-sm transition-colors {darkMode
                  ? 'border-gray-700 text-gray-300 hover:bg-gray-800 hover:border-gray-600'
                  : 'border-border text-foreground hover:bg-accent hover:border-ring'}"
                onclick={() => {
                  inputText = prompt;
                  sendMessage();
                }}
              >
                {prompt}
              </button>
            {/each}
          </div>
        </div>
      {:else}
        {#each messages as msg (msg.id)}
          <div
            class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}"
          >
            <div
              class="max-w-[85%] rounded-2xl px-3.5 py-2.5 text-base leading-relaxed {msg.role ===
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
                  <Quote size={14} class="mt-0.5 shrink-0 opacity-60" />
                  <p class="text-sm opacity-80 italic line-clamp-3">
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
              class="max-w-[85%] rounded-2xl px-3.5 py-2.5 text-base leading-relaxed {darkMode
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
    <div
      class="p-3"
      style="padding-bottom: max(0.75rem, env(safe-area-inset-bottom));"
    >
      <div
        class="rounded-2xl border transition-colors {darkMode
          ? 'border-gray-700 bg-gray-800/50 focus-within:border-gray-600'
          : 'border-border bg-muted/50 focus-within:border-ring'}"
      >
        {#if pendingSelectedText}
          <div
            class="flex items-start gap-2 mx-3 mt-2.5 px-2.5 py-2 rounded-lg text-sm {darkMode
              ? 'bg-gray-700/60 text-gray-300'
              : 'bg-background text-muted-foreground'}"
          >
            <Quote size={14} class="mt-0.5 shrink-0 opacity-60" />
            <p class="flex-1 line-clamp-2 italic">{pendingSelectedText}</p>
            <button
              class="shrink-0 p-1 rounded hover:opacity-70"
              aria-label={m.companion_clear_selection()}
              onclick={clearPendingSelection}
            >
              <X size={14} />
            </button>
          </div>
        {/if}
        <textarea
          bind:this={inputEl}
          bind:value={inputText}
          placeholder={m.companion_input_placeholder()}
          rows={1}
          class="w-full resize-none bg-transparent px-3.5 py-2.5 text-base outline-none overflow-hidden {darkMode
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
            class="w-9 h-9 flex items-center justify-center rounded-full transition-colors {isStreaming ||
            !inputText.trim()
              ? darkMode
                ? 'text-gray-600 bg-gray-700'
                : 'text-muted-foreground/30 bg-muted'
              : darkMode
                ? 'text-white bg-blue-600 hover:bg-blue-500'
                : 'text-primary-foreground bg-primary hover:bg-primary/90'}"
            disabled={isStreaming || !inputText.trim()}
            aria-label={m.companion_send()}
            onclick={sendMessage}
          >
            <ArrowUp size={18} strokeWidth={2.5} />
          </button>
        </div>
      </div>
    </div>
  {/if}
</div>
