<script lang="ts">
  import { worksApi } from "$lib/api/works";
  import { coverUrl } from "$lib/api/client";
  import { authedSrc } from "$lib/actions/authedSrc";
  import { toastStore } from "$lib/stores/toast";
  import type { DuplicateGroup } from "$lib/types";
  import {
    BookOpen,
    Merge,
    SkipForward,
    Ban,
    CircleCheck,
    LoaderCircle,
  } from "@lucide/svelte";
  import { onMount } from "svelte";
  import * as m from "$lib/paraglide/messages.js";
  import * as Dialog from "$lib/components/ui/dialog";
  import { Button } from "$lib/components/ui/button";

  let allGroups = $state<DuplicateGroup[]>([]);
  let scanning = $state(false);
  let scanned = $state(false);
  let totalScanned = $state(0);
  let truncated = $state(false);
  let processing = $state(false);
  let mergingAll = $state(false);
  let showMergeAllConfirm = $state(false);
  let reviewIndex = $state(0);
  let reviewedCount = $state(0);

  onMount(() => scan());

  let currentGroup = $derived(
    allGroups.length > 0 && reviewIndex < allGroups.length
      ? allGroups[reviewIndex]
      : null,
  );
  let totalGroups = $derived(reviewedCount + allGroups.length);
  let progressPct = $derived(
    totalGroups > 0 ? Math.round((reviewedCount / totalGroups) * 100) : 0,
  );

  async function scan() {
    scanning = true;
    scanned = false;
    allGroups = [];
    reviewIndex = 0;
    reviewedCount = 0;
    try {
      const result = await worksApi.getSuggestions();
      allGroups = result.groups;
      totalScanned = result.total_books_scanned;
      truncated = result.truncated;
      scanned = true;
      if (truncated) {
        toastStore.warning(m.duplicates_scan_timeout());
      }
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      scanning = false;
    }
  }

  function advance() {
    reviewedCount++;
  }

  async function mergeCurrentGroup() {
    if (!currentGroup || processing) return;
    processing = true;
    try {
      const bookIds = currentGroup.books.map((b) => b.id);
      const work = await worksApi.create(bookIds);
      toastStore.success(m.duplicates_merged_toast({ title: work.title }));
      allGroups = allGroups.filter((_, i) => i !== reviewIndex);
      advance();
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      processing = false;
    }
  }

  function skipCurrentGroup() {
    if (!currentGroup || processing) return;
    const skipped = allGroups[reviewIndex];
    allGroups = [...allGroups.filter((_, i) => i !== reviewIndex), skipped];
    advance();
  }

  async function excludeCurrentGroup() {
    if (!currentGroup || processing) return;
    processing = true;
    try {
      const bookIds = currentGroup.books.map((b) => b.id);
      await worksApi.exclude(bookIds);
      toastStore.success(m.duplicates_not_duplicates_toast());
      allGroups = allGroups.filter((_, i) => i !== reviewIndex);
      advance();
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      processing = false;
    }
  }

  async function handleMergeAll() {
    showMergeAllConfirm = false;
    mergingAll = true;
    let merged = 0;
    const toMerge = [...allGroups];
    for (const group of toMerge) {
      try {
        await worksApi.create(group.books.map((b) => b.id));
        merged++;
      } catch {
        // skip failed
      }
    }
    allGroups = [];
    reviewIndex = 0;
    mergingAll = false;
    toastStore.success(
      m.duplicates_merged_toast({ title: `${merged} groups` }),
    );
  }
</script>

<div class="max-w-3xl mx-auto px-4 py-8">
  <!-- Header row: title + progress -->
  <div class="flex items-baseline justify-between mb-2">
    <h1 class="text-2xl font-bold">{m.duplicates_title()}</h1>
    {#if scanned && totalGroups > 0}
      <span class="text-sm text-muted-foreground">
        {m.duplicates_review_progress({
          current: reviewedCount,
          total: totalGroups,
        })}
      </span>
    {/if}
  </div>

  <!-- Thin progress bar (only when reviewing) -->
  {#if scanned && totalGroups > 0}
    <div class="w-full h-1 bg-secondary rounded-full overflow-hidden mb-6">
      <div
        class="h-full bg-primary rounded-full transition-all duration-300"
        style:width="{progressPct}%"
      ></div>
    </div>
  {:else}
    <div class="mb-6"></div>
  {/if}

  <!-- Merge All (only when there are groups) -->
  {#if scanned && allGroups.length > 0}
    <div class="flex justify-end mb-8">
      <button
        class="inline-flex items-center gap-2 px-3 py-1.5 border border-input bg-white rounded-md text-xs text-muted-foreground hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
        onclick={() => (showMergeAllConfirm = true)}
        disabled={mergingAll}
      >
        {#if mergingAll}
          <LoaderCircle size={14} class="animate-spin" />
          {m.duplicates_merging_all()}
        {:else}
          <Merge size={14} />
          {m.duplicates_merge_all()}
        {/if}
      </button>
    </div>
  {:else if !scanning}
    <div class="mb-8"></div>
  {/if}

  <!-- Loading -->
  {#if scanning}
    <div class="flex flex-col items-center gap-3 py-20">
      <LoaderCircle size={32} class="animate-spin text-muted-foreground" />
      <p class="text-muted-foreground">{m.duplicates_scanning()}</p>
    </div>
  {/if}

  <!-- Review content -->
  {#if scanned && !scanning && !mergingAll}
    {#if allGroups.length === 0}
      <!-- Done -->
      <div class="flex flex-col items-center gap-3 py-20 text-center">
        <CircleCheck size={48} class="text-muted-foreground/40" />
        <p class="text-muted-foreground text-lg">
          {reviewedCount > 0 ? m.duplicates_all_done() : m.duplicates_empty()}
        </p>
        <a href="/" class="text-sm text-primary hover:underline">
          {m.duplicates_back_to_library()}
        </a>
      </div>
    {:else if currentGroup}
      <!-- Current group card -->
      {#key reviewIndex + "-" + reviewedCount}
        <div class="border border-border rounded-xl p-6 bg-white">
          <p class="text-xs text-muted-foreground uppercase tracking-wide mb-5">
            {currentGroup.match_method === "fuzzy"
              ? m.duplicates_match_label_fuzzy({
                  count: currentGroup.books.length,
                })
              : m.duplicates_match_label_exact({
                  count: currentGroup.books.length,
                })}
          </p>

          <!-- Book covers -->
          <div class="flex gap-5 overflow-x-auto pb-3 justify-center">
            {#each currentGroup.books as book}
              <div class="flex-shrink-0 w-[160px]">
                <div
                  class="aspect-[2/3] mb-2 rounded-sm overflow-hidden bg-secondary book-shadow"
                >
                  {#if book.cover_path}
                    <img
                      use:authedSrc={coverUrl(book.id)}
                      alt="{book.display_title} cover"
                      class="w-full h-full object-cover"
                      loading="lazy"
                    />
                  {:else}
                    <div class="w-full h-full flex items-center justify-center">
                      <BookOpen size={28} class="text-muted-foreground/30" />
                    </div>
                  {/if}
                </div>
                <p class="text-sm font-medium line-clamp-2 text-center">
                  {book.display_title ?? m.common_untitled()}
                </p>
                <p
                  class="text-xs text-muted-foreground line-clamp-1 text-center"
                >
                  {book.display_authors?.join(", ") ?? ""}
                </p>
              </div>
            {/each}
          </div>

          <!-- Actions: right-aligned, consistent sizing -->
          <div
            class="flex items-center justify-end gap-2 mt-5 pt-4 border-t border-border/50"
          >
            <button
              class="inline-flex items-center gap-2 px-4 py-2 border border-input bg-white rounded-md text-sm font-medium text-muted-foreground hover:bg-accent disabled:opacity-50"
              onclick={excludeCurrentGroup}
              disabled={processing}
            >
              <Ban size={14} />
              {m.duplicates_not_duplicates()}
            </button>
            <button
              class="inline-flex items-center gap-2 px-4 py-2 border border-input bg-white rounded-md text-sm font-medium text-muted-foreground hover:bg-accent disabled:opacity-50"
              onclick={skipCurrentGroup}
              disabled={processing}
            >
              <SkipForward size={14} />
              {m.duplicates_skip()}
            </button>
            <button
              class="inline-flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
              onclick={mergeCurrentGroup}
              disabled={processing}
            >
              {#if processing}
                <LoaderCircle size={14} class="animate-spin" />
              {:else}
                <Merge size={14} />
              {/if}
              {m.duplicates_merge()}
            </button>
          </div>
        </div>
      {/key}
    {/if}
  {/if}
</div>

<!-- Merge All Confirmation -->
<Dialog.Root bind:open={showMergeAllConfirm}>
  <Dialog.Content class="sm:max-w-sm bg-white dark:bg-neutral-900">
    <Dialog.Header>
      <Dialog.Title>{m.duplicates_merge_all()}</Dialog.Title>
      <Dialog.Description>
        {m.duplicates_merge_all_confirm({ count: allGroups.length })}
      </Dialog.Description>
    </Dialog.Header>
    <Dialog.Footer>
      <Button
        variant="outline"
        class="rounded-xl"
        onclick={() => (showMergeAllConfirm = false)}
      >
        {m.common_cancel()}
      </Button>
      <Button class="rounded-xl" onclick={handleMergeAll}>
        {m.duplicates_merge_all()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
