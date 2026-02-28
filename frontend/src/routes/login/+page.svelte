<script lang="ts">
  import { goto } from '$app/navigation';
  import { authApi } from '$lib/api/auth';
  import { authStore } from '$lib/stores/auth';
  import { toastStore } from '$lib/stores/toast';

  let username = '';
  let password = '';
  let email = '';
  let showRegister = false;
  let loading = false;

  async function handleLogin() {
    if (!username || !password) return;
    loading = true;
    try {
      const token = await authApi.login(username, password);
      const user = await authApi.me(token.access_token);
      authStore.login(user, token.access_token);
      // Set cookie for server-side auth
      document.cookie = `token=${token.access_token}; path=/; SameSite=Lax`;
      toastStore.success('Welcome back, ' + user.username + '!');
      goto('/');
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function handleRegister() {
    if (!username || !password) return;
    loading = true;
    try {
      await authApi.register({ username, password, email: email || undefined });
      toastStore.success('Account created! Please log in.');
      showRegister = false;
      email = '';
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head>
  <title>BeePub - Login</title>
</svelte:head>

<div class="min-h-screen bg-gray-900 flex items-center justify-center px-4">
  <div class="bg-gray-800 rounded-xl p-8 w-full max-w-md shadow-xl">
    <div class="text-center mb-8">
      <h1 class="text-4xl font-bold text-amber-500">BeePub</h1>
      <p class="text-gray-400 mt-2">Your personal ebook library</p>
    </div>

    <div class="flex rounded-lg overflow-hidden mb-6 border border-gray-700">
      <button
        class="flex-1 py-2 text-sm font-medium transition-colors {!showRegister
          ? 'bg-amber-500 text-gray-900'
          : 'bg-gray-800 text-gray-400 hover:text-white'}"
        on:click={() => (showRegister = false)}
      >
        Login
      </button>
      <button
        class="flex-1 py-2 text-sm font-medium transition-colors {showRegister
          ? 'bg-amber-500 text-gray-900'
          : 'bg-gray-800 text-gray-400 hover:text-white'}"
        on:click={() => (showRegister = true)}
      >
        Register
      </button>
    </div>

    {#if !showRegister}
      <form on:submit|preventDefault={handleLogin} class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-300 mb-1" for="username">Username</label>
          <input
            id="username"
            type="text"
            bind:value={username}
            class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-amber-500"
            placeholder="Enter username"
            required
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-300 mb-1" for="password">Password</label>
          <input
            id="password"
            type="password"
            bind:value={password}
            class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-amber-500"
            placeholder="Enter password"
            required
          />
        </div>
        <button
          type="submit"
          disabled={loading}
          class="w-full bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-gray-900 font-semibold py-2 rounded-lg transition-colors"
        >
          {loading ? 'Logging in...' : 'Login'}
        </button>
      </form>
    {:else}
      <form on:submit|preventDefault={handleRegister} class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-300 mb-1" for="reg-username">Username</label>
          <input
            id="reg-username"
            type="text"
            bind:value={username}
            class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-amber-500"
            placeholder="Choose username"
            required
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-300 mb-1" for="reg-email">Email (optional)</label>
          <input
            id="reg-email"
            type="email"
            bind:value={email}
            class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-amber-500"
            placeholder="Enter email"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-300 mb-1" for="reg-password">Password</label>
          <input
            id="reg-password"
            type="password"
            bind:value={password}
            class="w-full bg-gray-700 border border-gray-600 rounded-lg px-3 py-2 text-white placeholder-gray-500 focus:outline-none focus:border-amber-500"
            placeholder="Choose password"
            required
          />
        </div>
        <button
          type="submit"
          disabled={loading}
          class="w-full bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-gray-900 font-semibold py-2 rounded-lg transition-colors"
        >
          {loading ? 'Creating account...' : 'Register'}
        </button>
      </form>
    {/if}
  </div>
</div>
