<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { authStore } from '$lib/stores/auth';
  import { UserRole } from '$lib/types';
  import { BookOpen, Library, BookMarked, LogOut, Settings, Menu, X } from 'lucide-svelte';

  let menuOpen = false;
  let userMenuOpen = false;

  function logout() {
    authStore.logout();
    goto('/login');
  }

  $: isAdmin = $authStore.user?.role === UserRole.Admin;
</script>

<nav class="fixed top-0 left-0 right-0 z-50 bg-gray-900 border-b border-gray-800 h-16">
  <div class="max-w-7xl mx-auto px-4 h-full flex items-center justify-between">
    <!-- Logo -->
    <a href="/" class="text-amber-500 font-bold text-xl flex items-center gap-2">
      <BookOpen size={24} />
      BeePub
    </a>

    <!-- Desktop nav -->
    <div class="hidden md:flex items-center gap-6">
      <a
        href="/"
        class="text-sm font-medium transition-colors {$page.url.pathname === '/' ? 'text-amber-500' : 'text-gray-400 hover:text-white'}"
      >
        Home
      </a>
      <a
        href="/libraries"
        class="text-sm font-medium transition-colors {$page.url.pathname.startsWith('/libraries') ? 'text-amber-500' : 'text-gray-400 hover:text-white'}"
      >
        Libraries
      </a>
      <a
        href="/bookshelves"
        class="text-sm font-medium transition-colors {$page.url.pathname.startsWith('/bookshelves') ? 'text-amber-500' : 'text-gray-400 hover:text-white'}"
      >
        Bookshelves
      </a>
      {#if isAdmin}
        <a
          href="/admin"
          class="text-sm font-medium transition-colors {$page.url.pathname.startsWith('/admin') ? 'text-amber-500' : 'text-gray-400 hover:text-white'}"
        >
          Admin
        </a>
      {/if}
    </div>

    <!-- User menu -->
    <div class="hidden md:flex items-center gap-4 relative">
      <button
        class="flex items-center gap-2 text-gray-300 hover:text-white transition-colors"
        on:click={() => (userMenuOpen = !userMenuOpen)}
      >
        <div class="w-8 h-8 rounded-full bg-amber-500 flex items-center justify-center text-gray-900 font-bold text-sm">
          {$authStore.user?.username?.charAt(0).toUpperCase() ?? '?'}
        </div>
        <span class="text-sm">{$authStore.user?.username}</span>
      </button>

      {#if userMenuOpen}
        <div
          class="absolute right-0 top-10 bg-gray-800 border border-gray-700 rounded-lg shadow-xl py-1 w-40"
          role="menu"
        >
          <button
            class="w-full text-left px-4 py-2 text-sm text-gray-300 hover:bg-gray-700 flex items-center gap-2"
            on:click={logout}
          >
            <LogOut size={14} />
            Logout
          </button>
        </div>
      {/if}
    </div>

    <!-- Mobile hamburger -->
    <button class="md:hidden text-gray-400" on:click={() => (menuOpen = !menuOpen)}>
      {#if menuOpen}
        <X size={24} />
      {:else}
        <Menu size={24} />
      {/if}
    </button>
  </div>

  <!-- Mobile menu -->
  {#if menuOpen}
    <div class="md:hidden bg-gray-900 border-t border-gray-800 px-4 py-4 flex flex-col gap-4">
      <a href="/" class="text-sm font-medium text-gray-300 hover:text-white" on:click={() => (menuOpen = false)}>Home</a>
      <a href="/libraries" class="text-sm font-medium text-gray-300 hover:text-white" on:click={() => (menuOpen = false)}>Libraries</a>
      <a href="/bookshelves" class="text-sm font-medium text-gray-300 hover:text-white" on:click={() => (menuOpen = false)}>Bookshelves</a>
      {#if isAdmin}
        <a href="/admin" class="text-sm font-medium text-gray-300 hover:text-white" on:click={() => (menuOpen = false)}>Admin</a>
      {/if}
      <button class="text-left text-sm font-medium text-red-400 hover:text-red-300 flex items-center gap-2" on:click={logout}>
        <LogOut size={14} /> Logout
      </button>
    </div>
  {/if}
</nav>

<!-- Close user menu on outside click -->
{#if userMenuOpen}
  <button
    class="fixed inset-0 z-40"
    aria-label="Close menu"
    on:click={() => (userMenuOpen = false)}
  ></button>
{/if}
