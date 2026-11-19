<script lang="ts">
  import { formatDate } from "#lib/format.ts";
  import { ChevronRight, Copy, Check, KeySquare, Trash2 } from "@lucide/svelte";
  import * as Dialog from "#lib/components/ui/dialog/index.ts";
  import { Input } from "#lib/components/ui/input/index.ts";
  import { Button } from "#lib/components/ui/button/index.ts";
  import * as Tabs from "#lib/components/ui/tabs/index.ts";
  import { getServerUrl } from "#lib/api/client.ts";
  import { tokensApi } from "#lib/api/tokens.ts";
  import type { ApiToken } from "#lib/types.ts";
  import { confirmDialog } from "#lib/stores/confirm.ts";
  import { toastStore } from "#lib/stores/toast.ts";
  import * as m from "#lib/paraglide/messages.js";

  let expanded = $state(false);
  let loaded = $state(false);
  let tokens = $state<ApiToken[]>([]);
  let newName = $state("");
  let creating = $state(false);
  // Shown once, in a modal right after creation — never retrievable
  // again, so the user must actively dismiss it.
  let freshToken = $state<string | null>(null);
  let showTokenDialog = $state(false);
  // Which copy button last succeeded: the bare token or a setup tab.
  let copied = $state<"token" | ConnectTab | null>(null);

  // Setup for the agents most people use, plus a prompt any other
  // agent can follow — the token alone leaves people stranded.
  type ConnectTab = "claude" | "codex" | "other";
  let connectTab = $state<ConnectTab>("claude");

  const mcpUrl = $derived(
    (getServerUrl() ||
      (typeof window !== "undefined" ? window.location.origin : "")) + "/mcp",
  );

  function connectSnippet(tab: ConnectTab, token: string): string {
    switch (tab) {
      case "claude":
        return `claude mcp add --transport http beepub ${mcpUrl} \\\n  --header "Authorization: Bearer ${token}"`;
      case "codex":
        return `[mcp_servers.beepub]\nurl = "${mcpUrl}"\nhttp_headers = { Authorization = "Bearer ${token}" }`;
      case "other":
        return m.profile_api_token_other_prompt({ url: mcpUrl, token });
    }
  }

  const connectHint: Record<ConnectTab, () => string> = {
    claude: m.profile_api_token_claude_hint,
    codex: m.profile_api_token_codex_hint,
    other: m.profile_api_token_other_hint,
  };

  async function load() {
    try {
      tokens = await tokensApi.list();
      loaded = true;
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }

  function toggle() {
    expanded = !expanded;
    if (expanded && !loaded) load();
  }

  async function create() {
    const name = newName.trim();
    if (!name) return;
    creating = true;
    try {
      const created = await tokensApi.create(name);
      freshToken = created.token;
      copied = null;
      connectTab = "claude";
      showTokenDialog = true;
      newName = "";
      tokens = [created, ...tokens];
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      creating = false;
    }
  }

  async function copyText(text: string, key: "token" | ConnectTab) {
    try {
      await navigator.clipboard.writeText(text);
      copied = key;
    } catch {
      toastStore.error(m.profile_api_token_copy_failed());
    }
  }

  async function revoke(token: ApiToken) {
    if (
      !(await confirmDialog({
        title: m.profile_api_token_revoke_confirm({ name: token.name }),
        description: m.profile_api_token_revoke_confirm_desc(),
        destructive: true,
      }))
    )
      return;
    try {
      await tokensApi.revoke(token.id);
      tokens = tokens.filter((t) => t.id !== token.id);
    } catch (e) {
      toastStore.error((e as Error).message);
    }
  }
</script>

<button
  class="flex items-center gap-3 px-4 py-3.5 w-full text-left hover:bg-secondary/50 transition-colors"
  onclick={toggle}
>
  <KeySquare size={20} class="text-muted-foreground shrink-0" />
  <span class="text-sm font-medium flex-1">{m.profile_api_tokens()}</span>
  <ChevronRight
    size={16}
    class="text-muted-foreground/50 transition-transform {expanded
      ? 'rotate-90'
      : ''}"
  />
</button>
{#if expanded}
  <div class="px-4 py-4 space-y-4">
    <p class="text-xs text-muted-foreground">
      {m.profile_api_tokens_hint()}
    </p>

    <form
      class="flex gap-2"
      onsubmit={(e) => {
        e.preventDefault();
        create();
      }}
    >
      <Input
        bind:value={newName}
        placeholder={m.profile_api_token_name_placeholder()}
        maxlength={100}
        autocapitalize="none"
        autocorrect="off"
        spellcheck={false}
        required
        class="flex-1"
      />
      <Button type="submit" disabled={creating} class="rounded-xl text-sm">
        {m.profile_api_token_create()}
      </Button>
    </form>

    {#if loaded && tokens.length === 0}
      <p class="text-xs text-muted-foreground text-center py-1">
        {m.profile_api_token_empty()}
      </p>
    {:else if tokens.length > 0}
      <ul class="space-y-2">
        {#each tokens as token (token.id)}
          <li
            class="flex items-center gap-3 rounded-lg bg-secondary/40 px-3 py-2.5"
          >
            <div class="flex-1 min-w-0">
              <div class="flex items-baseline gap-2 min-w-0">
                <p class="text-sm font-medium truncate">{token.name}</p>
                <span
                  class="font-mono text-[11px] text-muted-foreground shrink-0"
                  >{token.token_prefix}…</span
                >
              </div>
              <p class="text-xs text-muted-foreground mt-0.5">
                {formatDate(token.created_at, "numeric")} · {token.last_used_at
                  ? m.profile_api_token_last_used({
                      date: formatDate(token.last_used_at, "numeric"),
                    })
                  : m.profile_api_token_never_used()}
              </p>
            </div>
            <Button
              variant="ghost"
              size="icon"
              class="shrink-0 text-muted-foreground hover:text-destructive"
              aria-label={m.profile_api_token_revoke()}
              onclick={() => revoke(token)}
            >
              <Trash2 size={16} />
            </Button>
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/if}

{#snippet copyButton(text: string, key: "token" | ConnectTab)}
  <Button
    variant="ghost"
    size="icon"
    class="absolute top-1 right-1 size-7 bg-background/80 text-muted-foreground hover:text-foreground"
    aria-label={copied === key
      ? m.profile_api_token_copied()
      : m.profile_api_token_copy()}
    onclick={() => copyText(text, key)}
  >
    {#if copied === key}
      <Check size={14} class="text-primary" />
    {:else}
      <Copy size={14} />
    {/if}
  </Button>
{/snippet}

<Dialog.Root
  bind:open={showTokenDialog}
  onOpenChange={(open) => {
    if (!open) {
      freshToken = null;
      copied = null;
    }
  }}
>
  <Dialog.Content class="sm:max-w-lg bg-popover">
    <Dialog.Header>
      <Dialog.Title>{m.profile_api_token_created_title()}</Dialog.Title>
      <Dialog.Description>
        {m.profile_api_token_show_once()}
      </Dialog.Description>
    </Dialog.Header>
    <div class="relative">
      <code
        class="block text-[11px] leading-5 whitespace-nowrap overflow-x-auto select-all bg-background rounded-sm py-2 pl-2.5 pr-10 border border-border"
        >{freshToken}</code
      >
      {@render copyButton(freshToken ?? "", "token")}
    </div>
    {#if freshToken}
      <div class="space-y-2 min-w-0">
        <p class="text-sm font-medium">
          {m.profile_api_token_connect_title()}
        </p>
        <Tabs.Root
          value={connectTab}
          onValueChange={(v) => (connectTab = v as ConnectTab)}
        >
          <Tabs.List class="w-full">
            <Tabs.Trigger value="claude">Claude Code</Tabs.Trigger>
            <Tabs.Trigger value="codex">Codex</Tabs.Trigger>
            <Tabs.Trigger value="other"
              >{m.profile_api_token_tab_other()}</Tabs.Trigger
            >
          </Tabs.List>
        </Tabs.Root>
        <p class="text-xs text-muted-foreground">
          {connectHint[connectTab]()}
        </p>
        <div class="relative">
          <pre
            class="text-[11px] leading-5 whitespace-pre-wrap [overflow-wrap:anywhere] select-all bg-background rounded-sm py-2 pl-2.5 pr-10 border border-border font-mono">{connectSnippet(
              connectTab,
              freshToken,
            )}</pre>
          {@render copyButton(
            connectSnippet(connectTab, freshToken),
            connectTab,
          )}
        </div>
      </div>
    {/if}
    <Dialog.Footer>
      <Button class="rounded-xl" onclick={() => (showTokenDialog = false)}>
        {m.common_close()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
