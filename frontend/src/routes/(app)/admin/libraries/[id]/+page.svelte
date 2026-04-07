<script lang="ts">
  import { onMount } from "svelte";
  import { page } from "$app/state";
  import { librariesApi } from "$lib/api/libraries";
  import { toastStore } from "$lib/stores/toast";
  import { Input } from "$lib/components/ui/input";
  import { Textarea } from "$lib/components/ui/textarea";
  import { Button } from "$lib/components/ui/button";
  import type { LibraryOut } from "$lib/types";
  import { Save } from "@lucide/svelte";
  import { FormSkeleton } from "$lib/components/skeletons";
  import BackButton from "$lib/components/BackButton.svelte";
  import * as m from "$lib/paraglide/messages.js";

  let libraryId = $derived(page.params.id as string);

  let library = $state<LibraryOut | null>(null);
  let loading = $state(true);
  let saving = $state(false);
  let editForm = $state({
    name: "",
    description: "",
  });

  onMount(async () => {
    await loadData();
  });

  async function loadData() {
    loading = true;
    try {
      library = await librariesApi.get(libraryId);
      if (library) {
        editForm = {
          name: library.name,
          description: library.description ?? "",
        };
      }
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function handleSave() {
    saving = true;
    try {
      library = await librariesApi.update(libraryId, {
        name: editForm.name,
        description: editForm.description,
      });
      toastStore.success("Library updated");
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      saving = false;
    }
  }
</script>

<svelte:head>
  <title>{library?.name ?? m.admin_libraries_heading()} - Admin - BeePub</title>
</svelte:head>

<div class="max-w-5xl mx-auto px-6 sm:px-8 py-6">
  <div class="mb-8">
    <div class="mb-1">
      <BackButton href="/admin/libraries" label={m.admin_libraries_heading()} />
    </div>
    <h1 class="text-3xl font-bold text-foreground">
      {library?.name ?? m.admin_libraries_heading()}
    </h1>
  </div>

  {#if loading}
    <FormSkeleton cards={1} />
  {:else if library}
    <!-- Edit form -->
    <div class="bg-card card-soft rounded-2xl p-6 mb-6">
      <h2 class="font-bold text-lg mb-4 text-foreground">
        {m.admin_library_settings()}
      </h2>
      <div class="space-y-4">
        <div class="space-y-1">
          <label
            class="block text-sm font-medium text-foreground"
            for="adm-lib-name">{m.admin_col_name()}</label
          >
          <Input
            id="adm-lib-name"
            bind:value={editForm.name}
            class="rounded-sm"
          />
        </div>
        <div class="space-y-1">
          <label
            class="block text-sm font-medium text-foreground"
            for="adm-lib-desc">{m.admin_col_description()}</label
          >
          <Textarea
            id="adm-lib-desc"
            bind:value={editForm.description}
            class="rounded-sm bg-background"
            rows={3}
          />
        </div>
        <Button disabled={saving} class="w-fit rounded-xl" onclick={handleSave}>
          <Save size={16} />
          {saving ? m.admin_library_saving() : m.common_save()}
        </Button>
      </div>
    </div>
  {/if}
</div>
