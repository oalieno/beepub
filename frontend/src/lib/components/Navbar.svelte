<script lang="ts">
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";
  import { authStore } from "$lib/stores/auth";
  import { UserRole } from "$lib/types";
  import { LogOut, Menu, X, Dices, Search } from "@lucide/svelte";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu";
  import * as Avatar from "$lib/components/ui/avatar";
  import { Separator } from "$lib/components/ui/separator";
  import SearchModal from "./SearchModal.svelte";

  let searchOpen = $state(false);
  let menuOpen = $state(false);
  let mobileMenuEl: HTMLElement | undefined = $state();
  let hamburgerEl: HTMLElement | undefined = $state();

  function handleClickOutside(e: PointerEvent) {
    if (!menuOpen) return;
    const target = e.target as Node;
    if (mobileMenuEl?.contains(target)) return;
    if (hamburgerEl?.contains(target)) return;
    menuOpen = false;
  }

  function logout() {
    authStore.logout();
    goto("/login");
  }

  let isAdmin = $derived($authStore.user?.role === UserRole.Admin);

  const navLinks = $derived([
    { href: "/", label: "Home", active: $page.url.pathname === "/" },
    {
      href: "/my-books",
      label: "My Books",
      active: $page.url.pathname.startsWith("/my-books"),
    },
    {
      href: "/libraries",
      label: "Libraries",
      active: $page.url.pathname.startsWith("/libraries"),
    },
    {
      href: "/bookshelves",
      label: "Shelves",
      active: $page.url.pathname.startsWith("/bookshelves"),
    },
    {
      href: "/highlights",
      label: "Highlights",
      active: $page.url.pathname.startsWith("/highlights"),
    },
    {
      href: "/discover",
      label: "Discover",
      active: $page.url.pathname.startsWith("/discover"),
    },
    ...(isAdmin
      ? [
          {
            href: "/admin",
            label: "Admin",
            active: $page.url.pathname.startsWith("/admin"),
          },
        ]
      : []),
  ]);
</script>

<svelte:window
  onpointerdown={handleClickOutside}
  onkeydown={(e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "k") {
      e.preventDefault();
      searchOpen = !searchOpen;
    }
  }}
/>

<nav
  class="fixed top-0 left-0 right-0 z-50 h-16 bg-background/80 backdrop-blur-md border-b border-border/50"
>
  <div
    class="max-w-6xl mx-auto px-4 sm:px-6 h-full flex items-center justify-between"
  >
    <!-- Logo -->
    <a href="/" class="flex items-center gap-2 group">
      <img src="/logo.png" alt="BeePub" class="h-9 w-9 object-contain" />
      <span
        class="text-xl font-bold tracking-tight"
        style="font-family: var(--font-heading)">BeePub</span
      >
    </a>

    <!-- Desktop nav — pill tabs -->
    <div
      class="hidden md:flex items-center bg-card card-soft rounded-full px-1.5 py-1.5 gap-1"
    >
      {#each navLinks as link}
        <a
          href={link.href}
          class="px-5 py-2 rounded-full text-sm font-medium transition-all duration-200 {link.active
            ? 'bg-primary text-primary-foreground shadow-sm'
            : 'text-muted-foreground hover:text-foreground hover:bg-secondary'}"
        >
          {link.label}
        </a>
      {/each}
    </div>

    <!-- Right side -->
    <div class="hidden md:flex items-center gap-3">
      <button
        class="p-2 rounded-lg transition-colors text-muted-foreground hover:text-foreground hover:bg-secondary"
        onclick={() => (searchOpen = true)}
        title="Search (⌘K)"
      >
        <Search size={20} />
      </button>
      <a
        href="/gacha"
        class="p-2 rounded-lg transition-colors {$page.url.pathname === '/gacha'
          ? 'bg-primary/10 text-primary'
          : 'text-muted-foreground hover:text-foreground hover:bg-secondary'}"
        title="抽書"
      >
        <Dices size={20} />
      </a>
      <DropdownMenu.Root>
        <DropdownMenu.Trigger>
          <button
            class="flex items-center gap-2.5 hover:opacity-80 transition-opacity"
          >
            <Avatar.Root class="h-8 w-8">
              <Avatar.Fallback
                class="bg-primary text-primary-foreground text-xs font-semibold"
              >
                {$authStore.user?.username?.charAt(0).toUpperCase() ?? "?"}
              </Avatar.Fallback>
            </Avatar.Root>
          </button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Content align="end" class="w-44">
          <div class="px-3 py-2 border-b border-border">
            <p class="text-sm font-medium">{$authStore.user?.username}</p>
          </div>
          <DropdownMenu.Item
            onclick={logout}
            class="gap-2 text-destructive focus:text-destructive"
          >
            <LogOut size={14} />
            Logout
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Root>
    </div>

    <!-- Mobile right side -->
    <div class="md:hidden flex items-center gap-1">
      <button
        class="p-2 rounded-lg transition-colors text-muted-foreground hover:text-foreground hover:bg-secondary"
        onclick={() => (searchOpen = true)}
      >
        <Search size={20} />
      </button>
      <a
        href="/gacha"
        class="p-2 rounded-lg transition-colors {$page.url.pathname === '/gacha'
          ? 'bg-primary/10 text-primary'
          : 'text-muted-foreground hover:text-foreground hover:bg-secondary'}"
      >
        <Dices size={20} />
      </a>
      <button
        bind:this={hamburgerEl}
        class="p-2 text-foreground rounded-lg hover:bg-secondary transition-colors"
        onclick={() => (menuOpen = !menuOpen)}
      >
        {#if menuOpen}
          <X size={22} />
        {:else}
          <Menu size={22} />
        {/if}
      </button>
    </div>
  </div>

  <!-- Mobile menu -->
  {#if menuOpen}
    <div
      bind:this={mobileMenuEl}
      class="md:hidden bg-card card-soft mx-4 mt-2 rounded-2xl px-3 py-3 flex flex-col gap-1"
    >
      {#each navLinks as link}
        <a
          href={link.href}
          class="px-4 py-2.5 rounded-xl text-sm font-medium transition-colors {link.active
            ? 'bg-primary text-primary-foreground'
            : 'text-muted-foreground hover:text-foreground hover:bg-secondary'}"
          onclick={() => (menuOpen = false)}
        >
          {link.label}
        </a>
      {/each}
      <Separator class="my-1.5" />
      <button
        class="px-4 py-2.5 rounded-xl text-sm font-medium text-destructive hover:bg-destructive/10 flex items-center gap-2 text-left"
        onclick={logout}
      >
        <LogOut size={14} /> Logout
      </button>
    </div>
  {/if}
</nav>

<SearchModal bind:open={searchOpen} />
