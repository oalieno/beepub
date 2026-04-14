<script lang="ts">
  import { page } from "$app/state";
  import { authStore } from "$lib/stores/auth";
  import { sidebarCollapsed, toggleSidebar } from "$lib/stores/sidebar";
  import { isNative } from "$lib/platform";
  import { isOnline } from "$lib/services/network";
  import { toastStore } from "$lib/stores/toast";
  import * as m from "$lib/paraglide/messages.js";
  import {
    Home,
    BookOpen,
    Library,
    BookCopy,
    ShelvingUnit,
    Highlighter,
    Compass,
    Search as SearchIcon,
    Dices,
    Download,
    PanelLeftClose,
    PanelLeftOpen,
  } from "@lucide/svelte";
  import * as Avatar from "$lib/components/ui/avatar";
  import { Separator } from "$lib/components/ui/separator";

  let { onSearchOpen }: { onSearchOpen: () => void } = $props();

  let online = $derived($isOnline);
  let collapsed = $derived($sidebarCollapsed);

  const navLinks = $derived([
    {
      href: "/",
      label: m.nav_home(),
      icon: Home,
      active: page.url.pathname === "/",
      requiresOnline: false,
    },
    {
      href: "/my-books",
      label: m.nav_my_books(),
      icon: BookOpen,
      active: page.url.pathname.startsWith("/my-books"),
      requiresOnline: true,
    },
    {
      href: "/all-books",
      label: m.nav_all_books(),
      icon: BookCopy,
      active: page.url.pathname.startsWith("/all-books"),
      requiresOnline: true,
    },
    {
      href: "/libraries",
      label: m.nav_libraries(),
      icon: Library,
      active: page.url.pathname.startsWith("/libraries"),
      requiresOnline: true,
    },
    {
      href: "/bookshelves",
      label: m.nav_shelves(),
      icon: ShelvingUnit,
      active: page.url.pathname.startsWith("/bookshelves"),
      requiresOnline: true,
    },
    {
      href: "/highlights",
      label: m.nav_highlights(),
      icon: Highlighter,
      active: page.url.pathname.startsWith("/highlights"),
      requiresOnline: true,
    },
    {
      href: "/discover",
      label: m.nav_discover(),
      icon: Compass,
      active: page.url.pathname.startsWith("/discover"),
      requiresOnline: true,
    },
    ...(isNative()
      ? [
          {
            href: "/downloads",
            label: m.nav_downloads(),
            icon: Download,
            active: page.url.pathname.startsWith("/downloads"),
            requiresOnline: false,
          },
        ]
      : []),
  ]);

  function handleDisabledClick(e: Event) {
    e.preventDefault();
    toastStore.info(m.nav_available_when_online());
  }
</script>

<nav
  class="hidden md:flex fixed left-0 top-0 bottom-0 z-40 flex-col bg-sidebar border-r border-sidebar-border transition-[width] duration-200 ease-in-out overflow-hidden {collapsed
    ? 'w-16'
    : 'w-[280px]'}"
  style="padding-top: env(safe-area-inset-top, 0px); padding-bottom: env(safe-area-inset-bottom, 0px); padding-left: env(safe-area-inset-left, 0px);"
  aria-label="Main navigation"
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
      aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
    >
      {#if collapsed}
        <PanelLeftOpen size={16} />
      {:else}
        <PanelLeftClose size={16} />
      {/if}
    </button>
  </div>

  <!-- Search -->
  <div class="px-3 mb-2">
    <button
      class="flex items-center w-full rounded-lg text-sm transition-colors {collapsed
        ? 'justify-center px-0 py-2.5 text-sidebar-foreground/70 hover:text-sidebar-foreground hover:bg-sidebar-accent/50'
        : 'gap-3 px-3 py-2 border border-sidebar-border bg-white'} {!online
        ? 'opacity-25 cursor-default'
        : collapsed
          ? ''
          : 'text-sidebar-foreground/50 hover:border-sidebar-foreground/30'}"
      onclick={() => {
        if (!online) {
          toastStore.info(m.nav_available_when_online());
          return;
        }
        onSearchOpen();
      }}
      aria-disabled={!online || undefined}
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

  <!-- Nav links -->
  <div class="flex-1 px-3 flex flex-col gap-0.5 overflow-y-auto">
    {#each navLinks as link}
      {@const disabled = !online && link.requiresOnline}
      <a
        href={disabled ? undefined : link.href}
        class="flex items-center gap-3 py-2.5 rounded-lg text-sm font-medium transition-colors {collapsed
          ? 'justify-center px-0'
          : 'px-3'} {disabled
          ? 'opacity-25 cursor-default'
          : link.active
            ? 'bg-sidebar-accent text-sidebar-accent-foreground'
            : 'text-sidebar-foreground/70 hover:text-sidebar-foreground hover:bg-sidebar-accent/50'}"
        aria-current={link.active ? "page" : undefined}
        aria-disabled={disabled || undefined}
        title={collapsed
          ? link.label
          : disabled
            ? m.nav_available_when_online()
            : undefined}
        onclick={disabled ? handleDisabledClick : undefined}
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

    <Separator class="my-2" />

    <!-- Gacha -->
    <a
      href={!online ? undefined : "/gacha"}
      class="flex items-center gap-3 py-2.5 rounded-lg text-sm font-medium transition-colors {collapsed
        ? 'justify-center px-0'
        : 'px-3'} {!online
        ? 'opacity-25 cursor-default'
        : page.url.pathname === '/gacha'
          ? 'bg-sidebar-accent text-sidebar-accent-foreground'
          : 'text-sidebar-foreground/70 hover:text-sidebar-foreground hover:bg-sidebar-accent/50'}"
      aria-disabled={!online || undefined}
      title={collapsed ? m.nav_gacha() : undefined}
      onclick={!online ? handleDisabledClick : undefined}
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
  </div>

  <!-- User section at bottom -->
  <div class="px-3 pb-4 pt-2 border-t border-sidebar-border">
    <a
      href="/profile"
      class="flex items-center gap-3 py-2.5 rounded-lg w-full text-left transition-colors {collapsed
        ? 'justify-center px-0'
        : 'px-3'} {page.url.pathname.startsWith('/profile') ||
      page.url.pathname.startsWith('/admin')
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
</nav>
