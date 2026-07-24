<script lang="ts">
  import { ChevronRight, Copy, Check, KeySquare, Trash2 } from "@lucide/svelte";
  import * as Dialog from "$lib/components/ui/dialog";
  import { Input } from "$lib/components/ui/input";
  import { Button } from "$lib/components/ui/button";
  import { tokensApi } from "$lib/api/tokens";
  import type { ApiToken } from "$lib/types";
  import { confirmDialog } from "$lib/stores/confirm";
  import { toastStore } from "$lib/stores/toast";
  import * as m from "$lib/paraglide/messages.js";

  let expanded = $state(false);
  let loaded = $state(false);
  let tokens = $state<ApiToken[]>([]);
  let newName = $state("");
  let creating = $state(false);
  // Shown once, in a modal right after creation — never retrievable
  // again, so the user must actively dismiss it.
  let freshToken = $state<string | null>(null);
  let showTokenDialog = $state(false);
  let copied = $state(false);

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
      copied = false;
      showTokenDialog = true;
      newName = "";
      tokens = [created, ...tokens];
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      creating = false;
    }
  }

  async function copyFresh() {
    if (!freshToken) return;
    try {
      await navigator.clipboard.writeText(freshToken);
      copied = true;
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

  function shortDate(iso: string): string {
    return new Date(iso).toLocaleDateString();
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
                {shortDate(token.created_at)} · {token.last_used_at
                  ? m.profile_api_token_last_used({
                      date: shortDate(token.last_used_at),
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

<Dialog.Root
  bind:open={showTokenDialog}
  onOpenChange={(open) => {
    if (!open) {
      freshToken = null;
      copied = false;
    }
  }}
>
  <Dialog.Content class="sm:max-w-md bg-popover">
    <Dialog.Header>
      <Dialog.Title>{m.profile_api_token_created_title()}</Dialog.Title>
      <Dialog.Description>
        {m.profile_api_token_show_once()}
      </Dialog.Description>
    </Dialog.Header>
    <div class="flex items-center gap-2">
      <code
        class="flex-1 min-w-0 text-[11px] whitespace-nowrap overflow-x-auto select-all bg-background rounded-sm px-2.5 py-2 border border-border"
        >{freshToken}</code
      >
      <Button
        variant="outline"
        size="icon"
        class="shrink-0"
        aria-label={copied
          ? m.profile_api_token_copied()
          : m.profile_api_token_copy()}
        onclick={copyFresh}
      >
        {#if copied}
          <Check size={16} class="text-primary" />
        {:else}
          <Copy size={16} />
        {/if}
      </Button>
    </div>
    <Dialog.Footer>
      <Button class="rounded-xl" onclick={() => (showTokenDialog = false)}>
        {m.common_close()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
