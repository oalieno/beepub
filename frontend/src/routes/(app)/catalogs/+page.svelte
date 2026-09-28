<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { authStore } from "$lib/stores/auth";
  import { UserRole } from "$lib/types";
  import { toastStore } from "$lib/stores/toast";
  import { confirmDialog } from "$lib/stores/confirm";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import * as Dialog from "$lib/components/ui/dialog";
  import {
    Rss,
    Plus,
    Pencil,
    Trash2,
    Lock,
    ChevronRight,
  } from "@lucide/svelte";
  import * as m from "$lib/paraglide/messages.js";
  import {
    catalogSide,
    listCatalogs,
    removeCatalog,
    saveCatalog,
    type CatalogInfo,
  } from "$lib/opds/catalogs";

  // Device catalogs (local mode) download onto the device; the server's
  // are shared and only admins manage them.
  const side = catalogSide();
  let canManage = $derived(
    side === "device" || $authStore.user?.role === UserRole.Admin,
  );

  let catalogs = $state<CatalogInfo[]>([]);
  let loading = $state(true);

  let dialogOpen = $state(false);
  let editing = $state<CatalogInfo | null>(null);
  let formName = $state("");
  let formUrl = $state("");
  let formUsername = $state("");
  let formPassword = $state("");
  let formError = $state("");
  let saving = $state(false);

  function hostOf(url: string): string {
    try {
      return new URL(url).host;
    } catch {
      return url;
    }
  }

  async function loadCatalogs() {
    try {
      catalogs = await listCatalogs(side);
    } catch (err) {
      toastStore.error((err as Error).message);
    } finally {
      loading = false;
    }
  }

  function openAdd() {
    editing = null;
    formName = "";
    formUrl = "";
    formUsername = "";
    formPassword = "";
    formError = "";
    dialogOpen = true;
  }

  function openEdit(e: MouseEvent, catalog: CatalogInfo) {
    e.stopPropagation();
    e.preventDefault();
    editing = catalog;
    formName = catalog.name;
    formUrl = catalog.url;
    formUsername = catalog.username ?? "";
    // The server never sends a password back; blank keeps it.
    formPassword = catalog.password ?? "";
    formError = "";
    dialogOpen = true;
  }

  async function handleSave() {
    formError = "";
    const url = formUrl.trim();
    let parsed: URL;
    try {
      parsed = new URL(url);
    } catch {
      formError = m.catalogs_url_invalid();
      return;
    }
    // The app reaches catalogs itself and iOS allows https only; the
    // server fetches for us, and a home-network catalog is often http.
    const schemes = side === "device" ? ["https:"] : ["https:", "http:"];
    if (!schemes.includes(parsed.protocol)) {
      formError =
        side === "device"
          ? m.catalogs_url_invalid()
          : m.catalogs_server_url_invalid();
      return;
    }
    saving = true;
    try {
      const input = {
        name: formName.trim() || parsed.host,
        url,
        username: formUsername,
        password: formPassword,
      };
      const saved = await saveCatalog(side, editing?.id ?? null, input);
      if (saved) {
        catalogs = editing
          ? catalogs.map((c) => (c.id === saved.id ? saved : c))
          : [...catalogs, saved];
      }
      dialogOpen = false;
    } catch (err) {
      formError = (err as Error).message;
    } finally {
      saving = false;
    }
  }

  async function handleDelete(e: MouseEvent, catalog: CatalogInfo) {
    e.stopPropagation();
    e.preventDefault();
    if (
      !(await confirmDialog({
        title:
          side === "device"
            ? m.catalogs_delete_confirm({ name: catalog.name })
            : m.catalogs_server_delete_confirm({ name: catalog.name }),
        destructive: true,
      }))
    )
      return;
    try {
      await removeCatalog(side, catalog.id);
      catalogs = catalogs.filter((c) => c.id !== catalog.id);
      toastStore.success(m.catalogs_deleted());
    } catch (err) {
      toastStore.error((err as Error).message);
    }
  }

  onMount(loadCatalogs);
</script>

<svelte:head>
  <title>{m.catalogs_page_title()}</title>
</svelte:head>

<div class="max-w-5xl mx-auto px-6 sm:px-8 py-6">
  {#if loading}
    <!-- Preferences read is quick; avoid a skeleton flash. -->
    <div class="py-24"></div>
  {:else}
    {#if canManage}
      <div class="flex items-center justify-end gap-3 mb-6">
        <Button size="sm" onclick={openAdd}>
          <Plus size={16} />
          {m.catalogs_add()}
        </Button>
      </div>
    {/if}

    {#if catalogs.length === 0}
      <div class="flex flex-col items-center justify-center py-24 text-center">
        <div class="mb-4 p-3 bg-primary/10 rounded-xl">
          <Rss class="text-primary/50" size={28} />
        </div>
        <p class="text-foreground text-lg font-medium mb-2">
          {m.catalogs_empty()}
        </p>
        <p class="text-muted-foreground text-sm max-w-xs mb-6">
          {side === "device"
            ? m.catalogs_empty_subtitle()
            : canManage
              ? m.catalogs_server_empty_subtitle()
              : m.catalogs_server_empty_reader()}
        </p>
      </div>
    {:else}
      <div class="space-y-3">
        {#each catalogs as catalog (catalog.id)}
          <div
            role="button"
            tabindex="0"
            class="w-full bg-card card-soft rounded-2xl p-4 flex items-center gap-3 cursor-pointer group"
            style="-webkit-tap-highlight-color: transparent;"
            onclick={() => goto(`/catalogs/${catalog.id}`)}
            onkeydown={(e) =>
              e.key === "Enter" && goto(`/catalogs/${catalog.id}`)}
          >
            <div class="p-2.5 bg-primary/10 rounded-xl shrink-0">
              <Rss class="text-primary" size={18} />
            </div>
            <div class="flex-1 min-w-0">
              <h3 class="font-medium text-sm truncate text-foreground">
                {catalog.name}
              </h3>
              <p
                class="text-muted-foreground text-xs truncate flex items-center gap-1 mt-0.5"
              >
                {#if catalog.hasCredentials}
                  <Lock size={10} class="shrink-0" />
                {/if}
                {hostOf(catalog.url)}
              </p>
            </div>
            {#if canManage}
              <button
                class="p-2 text-muted-foreground hover:text-foreground transition-colors"
                style="-webkit-tap-highlight-color: transparent;"
                title={m.catalogs_edit()}
                onclick={(e) => openEdit(e, catalog)}
              >
                <Pencil size={15} />
              </button>
              <button
                class="p-2 text-muted-foreground hover:text-destructive transition-colors"
                style="-webkit-tap-highlight-color: transparent;"
                title={m.catalogs_delete()}
                onclick={(e) => handleDelete(e, catalog)}
              >
                <Trash2 size={15} />
              </button>
            {/if}
            <ChevronRight size={16} class="text-muted-foreground shrink-0" />
          </div>
        {/each}
      </div>
    {/if}
  {/if}
</div>

<Dialog.Root bind:open={dialogOpen}>
  <Dialog.Content class="sm:max-w-md bg-popover">
    <Dialog.Header>
      <Dialog.Title>
        {editing ? m.catalogs_edit() : m.catalogs_add()}
      </Dialog.Title>
      <Dialog.Description
        >{side === "device"
          ? m.catalogs_dialog_desc()
          : m.catalogs_server_dialog_desc()}</Dialog.Description
      >
    </Dialog.Header>
    <form
      onsubmit={(e) => {
        e.preventDefault();
        handleSave();
      }}
      class="space-y-4"
    >
      <div class="space-y-1.5">
        <Label for="catalog-url">{m.catalogs_url_label()}</Label>
        <Input
          id="catalog-url"
          bind:value={formUrl}
          placeholder={side === "device"
            ? m.catalogs_url_placeholder()
            : m.catalogs_server_url_placeholder()}
          autocapitalize="none"
          autocomplete="url"
          autocorrect="off"
          spellcheck={false}
          inputmode="url"
          required
        />
      </div>
      <div class="space-y-1.5">
        <Label for="catalog-name">{m.catalogs_name_label()}</Label>
        <Input
          id="catalog-name"
          bind:value={formName}
          placeholder={hostOf(formUrl.trim()) || m.catalogs_name_label()}
          autocapitalize="none"
          autocorrect="off"
          spellcheck={false}
        />
      </div>
      <div class="space-y-1.5">
        <Label for="catalog-username">{m.catalogs_username_label()}</Label>
        <Input
          id="catalog-username"
          bind:value={formUsername}
          placeholder={m.catalogs_credentials_hint()}
          autocapitalize="none"
          autocomplete="off"
          autocorrect="off"
          spellcheck={false}
        />
      </div>
      <div class="space-y-1.5">
        <Label for="catalog-password">{m.catalogs_password_label()}</Label>
        <Input
          id="catalog-password"
          type="password"
          bind:value={formPassword}
          placeholder={side === "server" && editing?.hasCredentials
            ? m.catalogs_password_keep()
            : m.catalogs_credentials_hint()}
          autocomplete="off"
        />
      </div>
      {#if formError}
        <p class="text-sm text-red-600">{formError}</p>
      {/if}
      <Dialog.Footer>
        <Button
          variant="outline"
          class="rounded-xl"
          onclick={() => (dialogOpen = false)}>{m.common_cancel()}</Button
        >
        <Button type="submit" disabled={saving} class="rounded-xl">
          {m.common_save()}
        </Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
