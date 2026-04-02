<script lang="ts">
  import { goto } from "$app/navigation";
  import { authStore } from "$lib/stores/auth";
  import { isNative } from "$lib/platform";
  import { isOnline } from "$lib/services/network";
  import { toastStore } from "$lib/stores/toast";
  import { UserRole } from "$lib/types";
  import {
    BookOpen,
    ShelvingUnit,
    Highlighter,
    Settings,
    Download,
    Dices,
    LogOut,
    ChevronRight,
  } from "@lucide/svelte";
  import * as Avatar from "$lib/components/ui/avatar";

  let isAdmin = $derived($authStore.user?.role === UserRole.Admin);
  let online = $derived($isOnline);

  function handleDisabledClick(e: Event) {
    e.preventDefault();
    toastStore.info("Available when online");
  }

  async function logout() {
    await authStore.logout();
    goto("/login");
  }

  interface ProfileLink {
    href: string;
    label: string;
    icon: typeof BookOpen;
    requiresOnline: boolean;
    show?: boolean;
  }

  let mobileLinks = $derived<ProfileLink[]>([
    {
      href: "/my-books",
      label: "My Books",
      icon: BookOpen,
      requiresOnline: true,
    },
    {
      href: "/highlights",
      label: "Highlights",
      icon: Highlighter,
      requiresOnline: true,
    },
    {
      href: "/bookshelves",
      label: "Shelves",
      icon: ShelvingUnit,
      requiresOnline: true,
    },
    ...(isNative()
      ? [
          {
            href: "/downloads",
            label: "Downloads",
            icon: Download,
            requiresOnline: false,
          } satisfies ProfileLink,
        ]
      : []),
    { href: "/gacha", label: "Gacha", icon: Dices, requiresOnline: true },
    ...(isAdmin
      ? [
          {
            href: "/admin",
            label: "Admin",
            icon: Settings,
            requiresOnline: true,
          } satisfies ProfileLink,
        ]
      : []),
  ]);
</script>

<div class="max-w-5xl mx-auto px-6 sm:px-8 py-8">
  <!-- User info -->
  <div class="flex flex-col items-center gap-3 mb-8">
    <Avatar.Root class="h-20 w-20">
      <Avatar.Fallback
        class="bg-primary text-primary-foreground text-2xl font-semibold"
      >
        {$authStore.user?.username?.charAt(0).toUpperCase() ?? "?"}
      </Avatar.Fallback>
    </Avatar.Root>
    <div class="text-center">
      <h1 class="text-xl font-bold" style="font-family: var(--font-heading)">
        {$authStore.user?.username}
      </h1>
    </div>
  </div>

  <!-- Mobile nav links -->
  <div class="bg-card card-soft rounded-2xl overflow-hidden md:hidden">
    {#each mobileLinks as link, i}
      {@const disabled = !online && link.requiresOnline}
      {#if i > 0}
        <div class="flex justify-center">
          <div
            class="w-4/5 h-px bg-border"
            style="transform: scaleY(0.5);"
          ></div>
        </div>
      {/if}
      <a
        href={disabled ? undefined : link.href}
        class="flex items-center gap-3 px-4 py-3.5 transition-colors {disabled
          ? 'opacity-25 cursor-default'
          : 'hover:bg-secondary/50 active:bg-secondary'}"
        aria-disabled={disabled || undefined}
        onclick={disabled ? handleDisabledClick : undefined}
      >
        <link.icon size={20} class="text-muted-foreground shrink-0" />
        <span class="text-sm font-medium flex-1">{link.label}</span>
        <ChevronRight size={16} class="text-muted-foreground/50" />
      </a>
    {/each}
  </div>

  <!-- Desktop nav links -->
  {#if isAdmin}
    <div class="bg-card card-soft rounded-2xl overflow-hidden hidden md:block">
      <a
        href="/admin"
        class="flex items-center gap-3 px-4 py-3.5 transition-colors hover:bg-secondary/50 active:bg-secondary"
      >
        <Settings size={20} class="text-muted-foreground shrink-0" />
        <span class="text-sm font-medium flex-1">Admin</span>
        <ChevronRight size={16} class="text-muted-foreground/50" />
      </a>
    </div>
  {/if}

  <!-- Logout -->
  <div class="mt-4 bg-card card-soft rounded-2xl overflow-hidden">
    <button
      class="flex items-center gap-3 px-4 py-3.5 w-full text-left text-destructive hover:bg-destructive/5 active:bg-destructive/10 transition-colors"
      onclick={logout}
    >
      <LogOut size={20} class="shrink-0" />
      <span class="text-sm font-medium">Logout</span>
    </button>
  </div>
</div>
