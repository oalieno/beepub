<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { authStore } from '$lib/stores/auth';
  import { UserRole } from '$lib/types';
  import { BookOpen, LogOut, Menu, X, Bookmark } from '@lucide/svelte';
  import * as DropdownMenu from '$lib/components/ui/dropdown-menu';
  import * as Avatar from '$lib/components/ui/avatar';
  import { Separator } from '$lib/components/ui/separator';

  let menuOpen = $state(false);

  function logout() {
    authStore.logout();
    goto('/login');
  }

  let isAdmin = $derived($authStore.user?.role === UserRole.Admin);

  const navLinks = $derived([
    { href: '/', label: 'Home', active: $page.url.pathname === '/' },
    { href: '/libraries', label: 'Libraries', active: $page.url.pathname.startsWith('/libraries') },
    { href: '/bookshelves', label: 'Shelves', active: $page.url.pathname.startsWith('/bookshelves') },
    { href: '/highlights', label: 'Highlights', active: $page.url.pathname.startsWith('/highlights') },
    ...(isAdmin ? [{ href: '/admin', label: 'Admin', active: $page.url.pathname.startsWith('/admin') }] : []),
  ]);
</script>

<nav class="fixed top-0 left-0 right-0 z-50 h-16">
  <div class="max-w-6xl mx-auto px-4 sm:px-6 h-full flex items-center justify-between">
    <!-- Logo -->
    <a href="/" class="flex items-center gap-2.5 group">
      <div class="w-9 h-9 rounded-xl bg-primary/10 flex items-center justify-center">
        <BookOpen size={18} class="text-primary" />
      </div>
      <span class="text-xl font-bold tracking-tight" style="font-family: var(--font-heading)">BeePub</span>
    </a>

    <!-- Desktop nav — pill tabs -->
    <div class="hidden md:flex items-center bg-card card-soft rounded-full px-1.5 py-1.5 gap-1">
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
      <DropdownMenu.Root>
        <DropdownMenu.Trigger>
          <button class="flex items-center gap-2.5 hover:opacity-80 transition-opacity">
            <Avatar.Root class="h-8 w-8">
              <Avatar.Fallback class="bg-primary text-primary-foreground text-xs font-semibold">
                {$authStore.user?.username?.charAt(0).toUpperCase() ?? '?'}
              </Avatar.Fallback>
            </Avatar.Root>
          </button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Content align="end" class="w-44">
          <div class="px-3 py-2 border-b border-border">
            <p class="text-sm font-medium">{$authStore.user?.username}</p>
          </div>
          <DropdownMenu.Item onclick={logout} class="gap-2 text-destructive focus:text-destructive">
            <LogOut size={14} />
            Logout
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Root>
    </div>

    <!-- Mobile hamburger -->
    <button class="md:hidden p-2 text-foreground rounded-lg hover:bg-secondary transition-colors" onclick={() => (menuOpen = !menuOpen)}>
      {#if menuOpen}
        <X size={22} />
      {:else}
        <Menu size={22} />
      {/if}
    </button>
  </div>

  <!-- Mobile menu -->
  {#if menuOpen}
    <div class="md:hidden bg-card card-soft mx-4 mt-2 rounded-2xl px-3 py-3 flex flex-col gap-1">
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
