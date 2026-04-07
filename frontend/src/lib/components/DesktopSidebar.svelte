<script lang="ts">
  import { page } from "$app/state";
  import { authStore } from "$lib/stores/auth";
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
  } from "@lucide/svelte";
  import * as Avatar from "$lib/components/ui/avatar";
  import { Separator } from "$lib/components/ui/separator";

  let { onSearchOpen }: { onSearchOpen: () => void } = $props();

  let online = $derived($isOnline);

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
  class="hidden md:flex fixed left-0 top-0 bottom-0 z-40 w-[280px] flex-col bg-sidebar border-r border-sidebar-border"
  aria-label="Main navigation"
>
  <!-- Logo -->
  <a href="/" class="px-6 py-5 flex items-center gap-2.5">
    <img src="/logo.png" alt="BeePub" class="h-9 w-9 object-contain" />
    <span
      class="text-xl font-bold tracking-tight text-sidebar-foreground"
      style="font-family: var(--font-heading)">BeePub</span
    >
  </a>

  <!-- Search -->
  <div class="px-3 mb-2">
    <button
      class="flex items-center gap-3 w-full px-3 py-2 rounded-lg text-sm transition-colors border border-sidebar-border bg-white {!online
        ? 'opacity-25 cursor-default'
        : 'text-sidebar-foreground/50 hover:border-sidebar-foreground/30'}"
      onclick={() => {
        if (!online) {
          toastStore.info(m.nav_available_when_online());
          return;
        }
        onSearchOpen();
      }}
      aria-disabled={!online || undefined}
    >
      <SearchIcon size={16} />
      {m.nav_search()}
      <kbd
        class="ml-auto text-xs text-sidebar-foreground/30 bg-sidebar-accent/50 px-1.5 py-0.5 rounded"
        >⌘K</kbd
      >
    </button>
  </div>

  <!-- Nav links -->
  <div class="flex-1 px-3 flex flex-col gap-0.5 overflow-y-auto">
    {#each navLinks as link}
      {@const disabled = !online && link.requiresOnline}
      <a
        href={disabled ? undefined : link.href}
        class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors {disabled
          ? 'opacity-25 cursor-default'
          : link.active
            ? 'bg-sidebar-accent text-sidebar-accent-foreground'
            : 'text-sidebar-foreground/70 hover:text-sidebar-foreground hover:bg-sidebar-accent/50'}"
        aria-current={link.active ? "page" : undefined}
        aria-disabled={disabled || undefined}
        title={disabled ? m.nav_available_when_online() : undefined}
        onclick={disabled ? handleDisabledClick : undefined}
      >
        <link.icon size={20} />
        {link.label}
      </a>
    {/each}

    <Separator class="my-2" />

    <!-- Gacha -->
    <a
      href={!online ? undefined : "/gacha"}
      class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors {!online
        ? 'opacity-25 cursor-default'
        : page.url.pathname === '/gacha'
          ? 'bg-sidebar-accent text-sidebar-accent-foreground'
          : 'text-sidebar-foreground/70 hover:text-sidebar-foreground hover:bg-sidebar-accent/50'}"
      aria-disabled={!online || undefined}
      onclick={!online ? handleDisabledClick : undefined}
    >
      <Dices size={20} />
      {m.nav_gacha()}
    </a>
  </div>

  <!-- User section at bottom -->
  <div class="px-3 pb-4 pt-2 border-t border-sidebar-border">
    <a
      href="/profile"
      class="flex items-center gap-3 px-3 py-2.5 rounded-lg w-full text-left transition-colors {page.url.pathname.startsWith(
        '/profile',
      ) || page.url.pathname.startsWith('/admin')
        ? 'bg-sidebar-accent text-sidebar-accent-foreground'
        : 'hover:bg-sidebar-accent/50'}"
    >
      <Avatar.Root class="h-8 w-8 shrink-0">
        <Avatar.Fallback
          class="bg-sidebar-primary text-sidebar-primary-foreground text-xs font-semibold"
        >
          {$authStore.user?.username?.charAt(0).toUpperCase() ?? "?"}
        </Avatar.Fallback>
      </Avatar.Root>
      <span class="text-sm font-medium text-sidebar-foreground truncate">
        {$authStore.user?.username}
      </span>
    </a>
  </div>
</nav>
