<script lang="ts">
  import { goto } from "$app/navigation";
  import { authApi } from "$lib/api/auth";
  import { authStore } from "$lib/stores/auth";
  import { toastStore } from "$lib/stores/toast";
  import { BookOpen, Eye, EyeOff, Settings } from "@lucide/svelte";
  import { isNative } from "$lib/platform";
  import { getServerUrl } from "$lib/api/client";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import * as Card from "$lib/components/ui/card";
  import * as Tabs from "$lib/components/ui/tabs";

  let username = $state("");
  let password = $state("");
  let showRegister = $state(false);
  let loading = $state(false);
  let showPassword = $state(false);
  let errorMessage = $state("");

  async function handleLogin() {
    if (!username || !password) return;
    loading = true;
    errorMessage = "";
    try {
      const loginResponse = await authApi.login(username, password);
      authStore.login(loginResponse);
      toastStore.success("Welcome back, " + loginResponse.username + "!");
      goto("/");
    } catch (e) {
      errorMessage = (e as Error).message;
    } finally {
      loading = false;
    }
  }

  async function handleRegister() {
    if (!username || !password) return;
    loading = true;
    errorMessage = "";
    try {
      await authApi.register({ username, password });
      toastStore.success("Account created! Please log in.");
      showRegister = false;
    } catch (e) {
      errorMessage = (e as Error).message;
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head>
  <title>BeePub - Login</title>
</svelte:head>

<div class="min-h-screen flex items-center justify-center px-4">
  <div class="w-full max-w-sm">
    <!-- Logo -->
    <div class="text-center mb-8">
      <div
        class="w-16 h-16 rounded-2xl bg-primary/10 flex items-center justify-center mx-auto mb-4"
      >
        <BookOpen size={28} class="text-primary" />
      </div>
      <h1 class="text-3xl font-bold" style="font-family: var(--font-heading)">
        BeePub
      </h1>
      <p class="text-muted-foreground mt-1">Your personal ebook library</p>
      {#if isNative()}
        <button
          onclick={() => goto("/setup")}
          class="mt-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <Settings size={12} />
          {getServerUrl() || "No server configured"}
        </button>
      {/if}
    </div>

    <!-- Card -->
    <div class="bg-card card-soft rounded-2xl p-6">
      <Tabs.Root value={showRegister ? "register" : "login"} class="w-full">
        <Tabs.List
          class="grid w-full grid-cols-2 mb-6 bg-secondary rounded-full p-1"
        >
          <Tabs.Trigger
            value="login"
            onclick={() => (showRegister = false)}
            class="rounded-full data-[state=active]:bg-card data-[state=active]:shadow-sm"
            >Login</Tabs.Trigger
          >
          <Tabs.Trigger
            value="register"
            onclick={() => (showRegister = true)}
            class="rounded-full data-[state=active]:bg-card data-[state=active]:shadow-sm"
            >Register</Tabs.Trigger
          >
        </Tabs.List>

        <Tabs.Content value="login">
          <form
            onsubmit={(e) => {
              e.preventDefault();
              handleLogin();
            }}
            class="space-y-4"
          >
            <div class="space-y-1.5">
              <Label for="username" class="text-sm font-medium">Username</Label>
              <Input
                id="username"
                type="text"
                bind:value={username}
                placeholder="Enter username"
                required
                class="rounded-xl h-11"
              />
            </div>
            <div class="space-y-1.5">
              <Label for="password" class="text-sm font-medium">Password</Label>
              <div class="relative">
                <Input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  bind:value={password}
                  placeholder="Enter password"
                  required
                  class="rounded-xl h-11 pr-10"
                />
                <button
                  type="button"
                  onclick={() => (showPassword = !showPassword)}
                  class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                  tabindex={-1}
                >
                  {#if showPassword}
                    <EyeOff size={18} />
                  {:else}
                    <Eye size={18} />
                  {/if}
                </button>
              </div>
            </div>
            {#if errorMessage}
              <p class="text-sm text-red-600">{errorMessage}</p>
            {/if}
            <Button
              type="submit"
              disabled={loading}
              class="w-full rounded-xl h-11 text-sm font-semibold"
            >
              {loading ? "Logging in..." : "Login"}
            </Button>
          </form>
        </Tabs.Content>

        <Tabs.Content value="register">
          <form
            onsubmit={(e) => {
              e.preventDefault();
              handleRegister();
            }}
            class="space-y-4"
          >
            <div class="space-y-1.5">
              <Label for="reg-username" class="text-sm font-medium"
                >Username</Label
              >
              <Input
                id="reg-username"
                type="text"
                bind:value={username}
                placeholder="Choose username"
                required
                class="rounded-xl h-11"
              />
            </div>
            <div class="space-y-1.5">
              <Label for="reg-password" class="text-sm font-medium"
                >Password</Label
              >
              <div class="relative">
                <Input
                  id="reg-password"
                  type={showPassword ? "text" : "password"}
                  bind:value={password}
                  placeholder="Choose password"
                  required
                  class="rounded-xl h-11 pr-10"
                />
                <button
                  type="button"
                  onclick={() => (showPassword = !showPassword)}
                  class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                  tabindex={-1}
                >
                  {#if showPassword}
                    <EyeOff size={18} />
                  {:else}
                    <Eye size={18} />
                  {/if}
                </button>
              </div>
            </div>
            {#if errorMessage}
              <p class="text-sm text-red-600">{errorMessage}</p>
            {/if}
            <Button
              type="submit"
              disabled={loading}
              class="w-full rounded-xl h-11 text-sm font-semibold"
            >
              {loading ? "Creating account..." : "Register"}
            </Button>
          </form>
        </Tabs.Content>
      </Tabs.Root>
    </div>
  </div>
</div>
