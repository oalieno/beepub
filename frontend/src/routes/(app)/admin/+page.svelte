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
  } from "@lucide/svelte";
  import { DashboardSkeleton } from "$lib/components/skeletons";

  let stats = $state<AdminStats | null>(null);
  let loading = $state(true);

  interface AdminLink {
    href: string;
    label: string;
    icon: typeof Library;
  }

  const links: AdminLink[] = [
    { href: "/admin/libraries", label: "Libraries", icon: Library },
    { href: "/admin/users", label: "Users", icon: Users },
    { href: "/admin/calibre", label: "Calibre Import", icon: HardDrive },
    { href: "/admin/jobs", label: "Jobs", icon: ListChecks },
    { href: "/admin/reports", label: "Book Reports", icon: Flag },
    { href: "/admin/llm-usage", label: "LLM Usage", icon: Activity },
    { href: "/admin/settings", label: "Settings", icon: Settings },
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
  <title>Admin - BeePub</title>
</svelte:head>

<div class="max-w-5xl mx-auto px-6 sm:px-8 py-6">
  <div class="mb-6">
    <a
      href="/profile"
      class="text-muted-foreground hover:text-foreground text-sm mb-1 inline-block"
      >&larr; Profile</a
    >
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
          <span class="text-xs text-muted-foreground">Users</span>
        </div>
        <div class="flex-1 flex flex-col items-center py-3 px-2 gap-0.5">
          <span class="text-lg font-bold tabular-nums">{stats?.books ?? 0}</span
          >
          <span class="text-xs text-muted-foreground">Books</span>
        </div>
        <div class="flex-1 flex flex-col items-center py-3 px-2 gap-0.5">
          <span class="text-lg font-bold tabular-nums"
            >{stats?.libraries ?? 0}</span
          >
          <span class="text-xs text-muted-foreground">Libraries</span>
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
          <span class="text-sm font-medium flex-1">{link.label}</span>
          <ChevronRight size={16} class="text-muted-foreground/50" />
        </a>
      {/each}
    </div>
  {/if}
</div>
