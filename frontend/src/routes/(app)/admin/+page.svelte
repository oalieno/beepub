<script lang="ts">
  import { onMount } from "svelte";
  import { adminApi } from "$lib/api/admin";
  import { toastStore } from "$lib/stores/toast";
  import type { AdminStats } from "$lib/types";
  import {
    Users,
    BookOpen,
    Library,
    ChevronRight,
    HardDrive,
    Settings,
    ListChecks,
    Activity,
    Flag,
    Copy,
  } from "@lucide/svelte";
  import { DashboardSkeleton } from "$lib/components/skeletons";
  import BackButton from "$lib/components/BackButton.svelte";
  import * as m from "$lib/paraglide/messages.js";

  let stats = $state<AdminStats | null>(null);
  let loading = $state(true);

  interface AdminLink {
    href: string;
    label: () => string;
    icon: typeof Library;
  }

  const links: AdminLink[] = [
    {
      href: "/admin/libraries",
      label: () => m.admin_link_libraries(),
      icon: Library,
    },
    { href: "/admin/users", label: () => m.admin_link_users(), icon: Users },
    {
      href: "/admin/calibre",
      label: () => m.admin_link_calibre(),
      icon: HardDrive,
    },
    { href: "/admin/jobs", label: () => m.admin_link_jobs(), icon: ListChecks },
    { href: "/admin/reports", label: () => m.admin_link_reports(), icon: Flag },
    {
      href: "/admin/llm-usage",
      label: () => m.admin_link_llm_usage(),
      icon: Activity,
    },
    {
      href: "/admin/duplicates",
      label: () => m.admin_link_duplicates(),
      icon: Copy,
    },
    {
      href: "/admin/settings",
      label: () => m.admin_link_settings(),
      icon: Settings,
    },
  ];

  onMount(async () => {
    try {
      stats = await adminApi.getStats();
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  });
</script>

<svelte:head>
  <title>{m.admin_page_title()}</title>
</svelte:head>

<div class="max-w-5xl mx-auto px-6 sm:px-8 py-6">
  <div class="mb-6">
    <BackButton href="/profile" label={m.admin_back_to_profile()} />
  </div>

  {#if loading}
    <DashboardSkeleton />
  {:else}
    <!-- Stats -->
    <div class="bg-card card-soft rounded-2xl overflow-hidden mb-6">
      <div class="flex divide-x divide-border">
        <div class="flex-1 flex flex-col items-center py-3 px-2 gap-0.5">
          <span class="text-lg font-bold tabular-nums">{stats?.users ?? 0}</span
          >
          <span class="text-xs text-muted-foreground"
            >{m.admin_stat_users()}</span
          >
        </div>
        <div class="flex-1 flex flex-col items-center py-3 px-2 gap-0.5">
          <span class="text-lg font-bold tabular-nums">{stats?.books ?? 0}</span
          >
          <span class="text-xs text-muted-foreground"
            >{m.admin_stat_books()}</span
          >
        </div>
        <div class="flex-1 flex flex-col items-center py-3 px-2 gap-0.5">
          <span class="text-lg font-bold tabular-nums"
            >{stats?.libraries ?? 0}</span
          >
          <span class="text-xs text-muted-foreground"
            >{m.admin_stat_libraries()}</span
          >
        </div>
      </div>
    </div>

    <!-- Links -->
    <div class="bg-card card-soft rounded-2xl overflow-hidden">
      {#each links as link, i}
        {#if i > 0}
          <div class="flex justify-center">
            <div
              class="w-4/5 h-px bg-border"
              style="transform: scaleY(0.5);"
            ></div>
          </div>
        {/if}
        <a
          href={link.href}
          class="flex items-center gap-3 px-4 py-3.5 transition-colors hover:bg-secondary/50 active:bg-secondary"
        >
          <link.icon size={20} class="text-muted-foreground shrink-0" />
          <span class="text-sm font-medium flex-1">{link.label()}</span>
          <ChevronRight size={16} class="text-muted-foreground/50" />
        </a>
      {/each}
    </div>
  {/if}
</div>
