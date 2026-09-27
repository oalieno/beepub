<script lang="ts">
  import { page } from "$app/state";
  import { authStore } from "$lib/stores/auth";
  import { sidebarCollapsed, toggleSidebar } from "$lib/stores/sidebar";
  import { isNative } from "$lib/platform";
  import { activeLibraryHref } from "$lib/stores/activeLibrary";
  import * as m from "$lib/paraglide/messages.js";
  import {
    Search as SearchIcon,
    Dices,
    PanelLeftClose,
    PanelLeftOpen,
  } from "@lucide/svelte";
  import { isLocalMode } from "$lib/api/client";
  import { navLinks as buildNavLinks } from "$lib/nav";
  import * as Avatar from "$lib/components/ui/avatar";
  import { Separator } from "$lib/components/ui/separator";
  import { UserRole } from "$lib/types";

  let { onSearchOpen }: { onSearchOpen?: () => void } = $props();

  let collapsed = $derived($sidebarCollapsed);
  let isAdmin = $derived($authStore.user?.role === UserRole.Admin);
  // Mode switches are a full page load, so a one-time read is enough.
  const mode = isLocalMode() ? "local" : "server";

  // No per-link online gating: offline replaces this chrome with the
  // disconnect screen entirely, so every link rendered here is usable.
  const navLinks = $derived(
    buildNavLinks({
      mode,
      libraryHref: $activeLibraryHref,
      native: isNative(),
      admin: isAdmin,
    }).map((link) => ({ ...link, active: link.match(page.url.pathname) })),
  );
</script>

<nav
  class="hidden md:flex fixed left-0 top-0 bottom-0 z-40 flex-col bg-sidebar border-r border-sidebar-border transition-[width] duration-200 ease-in-out overflow-hidden {collapsed
    ? 'w-16'
    : 'w-[280px]'}"
  style="padding-top: env(safe-area-inset-top, 0px); padding-bottom: env(safe-area-inset-bottom, 0px); padding-left: env(safe-area-inset-left, 0px);"
  aria-label={m.nav_main_navigation()}
>
  <!-- Logo + Toggle -->
  <div
    class="py-5 flex items-center overflow-hidden whitespace-nowrap {collapsed
      ? 'px-3 flex-col gap-2'
      : 'px-6'}"
  >
    <a href="/" class="flex items-center gap-2.5 flex-shrink-0">
      <img
        src="/logo.png"
        alt="BeePub"
        class="h-9 w-9 object-contain flex-shrink-0"
      />
      {#if !collapsed}
        <span
          class="text-xl font-bold tracking-tight text-sidebar-foreground transition-opacity duration-100 opacity-100 delay-100"
          style="font-family: var(--font-heading)"
        >
          BeePub
        </span>
      {/if}
    </a>
    <button
      class="flex-shrink-0 p-1.5 rounded-md text-sidebar-foreground/40 hover:text-sidebar-foreground hover:bg-sidebar-accent/50 transition-colors {collapsed
        ? ''
        : 'ml-auto'}"
      onclick={toggleSidebar}
      aria-label={collapsed ? m.nav_expand_sidebar() : m.nav_collapse_sidebar()}
    >
      {#if collapsed}
        <PanelLeftOpen size={16} />
      {:else}
        <PanelLeftClose size={16} />
      {/if}
    </button>
  </div>

  <!-- Search, gacha and the account query the server: server mode only. -->
  {#if mode === "server"}
    <div class="px-3 mb-2">
      <button
        class="flex items-center w-full rounded-lg text-sm transition-colors {collapsed
          ? 'justify-center px-0 py-2.5 text-sidebar-foreground/70 hover:text-sidebar-foreground hover:bg-sidebar-accent/50'
          : 'gap-3 px-3 py-2 border border-sidebar-border bg-card text-sidebar-foreground/50 hover:border-sidebar-foreground/30'}"
        onclick={onSearchOpen}
        title={collapsed ? m.nav_search() : undefined}
      >
        <SearchIcon size={collapsed ? 20 : 16} class="flex-shrink-0" />
        {#if !collapsed}
          <span
            class="transition-opacity duration-100 {collapsed
              ? 'opacity-0'
              : 'opacity-100 delay-100'}"
          >
            {m.nav_search()}
          </span>
          <kbd
            class="ml-auto text-xs text-sidebar-foreground/30 bg-sidebar-accent/50 px-1.5 py-0.5 rounded"
          >
            ⌘K
          </kbd>
        {/if}
      </button>
    </div>
  {/if}

  <!-- Nav links -->
  <div class="flex-1 px-3 flex flex-col gap-0.5 overflow-y-auto">
    {#each navLinks as link}
      <a
        href={link.href}
        class="flex items-center gap-3 py-2.5 rounded-lg text-sm font-medium transition-colors {collapsed
          ? 'justify-center px-0'
          : 'px-3'} {link.active
          ? 'bg-sidebar-accent text-sidebar-accent-foreground'
          : 'text-sidebar-foreground/70 hover:text-sidebar-foreground hover:bg-sidebar-accent/50'}"
        aria-current={link.active ? "page" : undefined}
        title={collapsed ? link.label : undefined}
      >
        <link.icon size={20} class="flex-shrink-0" />
        {#if !collapsed}
          <span
            class="transition-opacity duration-100 whitespace-nowrap {collapsed
              ? 'opacity-0'
              : 'opacity-100 delay-100'}"
          >
            {link.label}
          </span>
        {/if}
      </a>
    {/each}

    {#if mode === "server"}
      <Separator class="my-2" />

      <!-- Gacha -->
      <a
        href="/gacha"
        class="flex items-center gap-3 py-2.5 rounded-lg text-sm font-medium transition-colors {collapsed
          ? 'justify-center px-0'
          : 'px-3'} {page.url.pathname === '/gacha'
          ? 'bg-sidebar-accent text-sidebar-accent-foreground'
          : 'text-sidebar-foreground/70 hover:text-sidebar-foreground hover:bg-sidebar-accent/50'}"
        title={collapsed ? m.nav_gacha() : undefined}
      >
        <Dices size={20} class="flex-shrink-0" />
        {#if !collapsed}
          <span
            class="transition-opacity duration-100 whitespace-nowrap {collapsed
              ? 'opacity-0'
              : 'opacity-100 delay-100'}"
          >
            {m.nav_gacha()}
          </span>
        {/if}
      </a>
    {/if}
  </div>

  <!-- User section at bottom -->
  {#if mode === "server"}
    <div class="px-3 pb-4 pt-2 border-t border-sidebar-border">
      <a
        href="/profile"
        class="flex items-center gap-3 py-2.5 rounded-lg w-full text-left transition-colors {collapsed
          ? 'justify-center px-0'
          : 'px-3'} {page.url.pathname.startsWith('/profile')
          ? 'bg-sidebar-accent text-sidebar-accent-foreground'
          : 'hover:bg-sidebar-accent/50'}"
        title={collapsed ? $authStore.user?.username : undefined}
      >
        <Avatar.Root class="h-8 w-8 shrink-0">
          <Avatar.Fallback
            class="bg-sidebar-primary text-sidebar-primary-foreground text-xs font-semibold"
          >
            {$authStore.user?.username?.charAt(0).toUpperCase() ?? "?"}
          </Avatar.Fallback>
        </Avatar.Root>
        {#if !collapsed}
          <span
            class="text-sm font-medium text-sidebar-foreground truncate transition-opacity duration-100 opacity-100 delay-100"
          >
            {$authStore.user?.username}
          </span>
        {/if}
      </a>
    </div>
  {/if}
</nav>
