<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { authApi } from "$lib/api/auth";
  import { authStore } from "$lib/stores/auth";
  import { toastStore } from "$lib/stores/toast";
  import * as m from "$lib/paraglide/messages.js";
  import { Eye, EyeOff, Info, Settings } from "@lucide/svelte";
  import { isNative } from "$lib/platform";
  import { getServerUrl, switchAppMode } from "$lib/api/client";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import * as Card from "$lib/components/ui/card";
  import * as Tabs from "$lib/components/ui/tabs";
  import { Skeleton } from "$lib/components/ui/skeleton";

  let username = $state("");
  let password = $state("");
  let showRegister = $state(false);
  let loading = $state(false);
  let showPassword = $state(false);
  let errorMessage = $state("");
  let registrationAllowed = $state(false);
  let firstUser = $state(false);
  let statusLoaded = $state(false);
  let demo = $state<{ username: string; password: string } | null>(null);

  onMount(async () => {
    try {
      const status = await authApi.registrationStatus();
      registrationAllowed = status.registration_enabled;
      firstUser = status.first_user;
      // The first-run view renders only the register form, so the error
      // message must follow the register condition.
      if (firstUser) showRegister = true;
      demo = status.demo ?? null;
    } catch {
      registrationAllowed = false;
    } finally {
      statusLoaded = true;
    }
  });

  async function handleDemoLogin() {
    if (!demo) return;
    username = demo.username;
    password = demo.password;
    await handleLogin();
  }

  async function handleLogin() {
    if (!username || !password) return;
    loading = true;
    errorMessage = "";
    try {
      const loginResponse = await authApi.login(username, password);
      authStore.login(loginResponse);
      toastStore.success(
        m.auth_welcome_back({ username: loginResponse.username }),
      );
      goto("/");
    } catch (e) {
      errorMessage = (e as Error).message;
    } finally {
      loading = false;
    }
  }

  async function handleRegister() {
    if (!username || !password) return;
    if (password.length < 8) {
      errorMessage = m.auth_password_too_short();
      return;
    }
    loading = true;
    errorMessage = "";
    try {
      await authApi.register({ username, password });
    } catch (e) {
      errorMessage = (e as Error).message;
      loading = false;
      return;
    }
    if (firstUser) {
      // Don't bounce the very first user back to a login form to retype
      // the credentials they chose two seconds ago.
      try {
        const loginResponse = await authApi.login(username, password);
        authStore.login(loginResponse);
        toastStore.success(
          m.auth_welcome_back({ username: loginResponse.username }),
        );
        goto("/");
        return;
      } catch {
        // The account exists but the follow-up login failed (rate limit,
        // network blip) — the server is no longer user-less, so fall back
        // to the plain login form.
        firstUser = false;
        showRegister = false;
        loading = false;
        toastStore.success(m.auth_account_created());
        return;
      }
    }
    toastStore.success(m.auth_account_created());
    showRegister = false;
    loading = false;
  }
</script>

{#snippet registerForm(submitLabel: string)}
  <form
    onsubmit={(e) => {
      e.preventDefault();
      handleRegister();
    }}
    class="space-y-4"
  >
    <div class="space-y-1.5">
      <Label for="reg-username" class="text-sm font-medium"
        >{m.auth_username()}</Label
      >
      <Input
        id="reg-username"
        type="text"
        bind:value={username}
        placeholder={m.auth_choose_username()}
        autocapitalize="none"
        autocomplete="username"
        autocorrect="off"
        spellcheck={false}
        inputmode="text"
        required
        class="rounded-xl h-11"
      />
    </div>
    <div class="space-y-1.5">
      <Label for="reg-password" class="text-sm font-medium"
        >{m.auth_password()}</Label
      >
      <div class="relative">
        <Input
          id="reg-password"
          type={showPassword ? "text" : "password"}
          bind:value={password}
          placeholder={m.auth_choose_password()}
          required
          class="rounded-xl h-11 pr-10"
        />
        <button
          aria-label={m.common_toggle_password()}
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
    {#if errorMessage && showRegister}
      <p class="text-sm text-red-600">{errorMessage}</p>
    {/if}
    <Button
      type="submit"
      disabled={loading}
      class="w-full rounded-xl h-11 text-sm font-semibold"
    >
      {loading ? m.auth_creating_account() : submitLabel}
    </Button>
  </form>
{/snippet}

{#snippet loginForm()}
  <form
    onsubmit={(e) => {
      e.preventDefault();
      handleLogin();
    }}
    class="space-y-4"
  >
    <div class="space-y-1.5">
      <Label for="username" class="text-sm font-medium"
        >{m.auth_username()}</Label
      >
      <Input
        id="username"
        type="text"
        bind:value={username}
        placeholder={m.auth_enter_username()}
        autocapitalize="none"
        autocomplete="username"
        autocorrect="off"
        spellcheck={false}
        inputmode="text"
        required
        class="rounded-xl h-11"
      />
    </div>
    <div class="space-y-1.5">
      <Label for="password" class="text-sm font-medium"
        >{m.auth_password()}</Label
      >
      <div class="relative">
        <Input
          id="password"
          type={showPassword ? "text" : "password"}
          bind:value={password}
          placeholder={m.auth_enter_password()}
          required
          class="rounded-xl h-11 pr-10"
        />
        <button
          aria-label={m.common_toggle_password()}
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
    {#if errorMessage && !showRegister}
      <p class="text-sm text-red-600">{errorMessage}</p>
    {/if}
    <Button
      type="submit"
      disabled={loading}
      class="w-full rounded-xl h-11 text-sm font-semibold"
    >
      {loading ? m.auth_logging_in() : m.auth_login()}
    </Button>
  </form>
{/snippet}

<svelte:head>
  <title>{m.auth_page_title()}</title>
</svelte:head>

<div class="min-h-screen flex items-center justify-center px-4">
  <div class="w-full max-w-sm">
    <!-- Logo -->
    <div class="text-center mb-8">
      <!-- The bee mascot, not a generic book — the first screen should
           already look like BeePub. -->
      <div
        class="w-16 h-16 rounded-2xl bg-primary/10 flex items-center justify-center mx-auto mb-4"
      >
        <img src="/logo.png" alt="" class="w-10 h-auto" draggable="false" />
      </div>
      <h1 class="text-3xl font-bold" style="font-family: var(--font-heading)">
        BeePub
      </h1>
      <p class="text-muted-foreground mt-1">{m.auth_subtitle()}</p>
      {#if isNative()}
        <button
          onclick={() => goto("/setup")}
          class="mt-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <Settings size={12} />
          {getServerUrl() || m.auth_no_server()}
        </button>
      {/if}
    </div>

    {#if demo}
      <div
        class="mb-4 rounded-2xl border border-primary/25 bg-primary/5 p-4 text-sm"
      >
        <p class="font-medium">{m.auth_demo_notice()}</p>
        <p class="text-muted-foreground mt-1">
          {m.auth_demo_credentials({
            username: demo.username,
            password: demo.password,
          })}
        </p>
        <Button
          variant="outline"
          class="mt-3 w-full rounded-xl h-10"
          disabled={loading}
          onclick={handleDemoLogin}
        >
          {m.auth_demo_login()}
        </Button>
      </div>
    {/if}

    <!-- Card -->
    <div class="bg-card card-soft rounded-2xl p-6">
      {#if !statusLoaded}
        <!-- Hold the card until we know which view this server needs —
             painting the login form first and swapping is exactly the
             first-run confusion this screen is meant to avoid. -->
        <div class="space-y-4" aria-hidden="true">
          <Skeleton class="h-11 w-full rounded-xl" />
          <Skeleton class="h-11 w-full rounded-xl" />
          <Skeleton class="h-11 w-full rounded-xl" />
        </div>
      {:else if firstUser}
        <h2 class="text-xl font-semibold text-center mb-4">
          {m.auth_first_run_title()}
        </h2>
        <div
          class="mb-5 flex gap-3 rounded-2xl border border-primary/25 bg-primary/5 p-4 text-sm text-muted-foreground"
        >
          <Info size={18} class="mt-0.5 shrink-0 text-primary" />
          <p>{m.auth_first_run_notice()}</p>
        </div>
        {@render registerForm(m.auth_first_run_submit())}
      {:else if registrationAllowed}
        <Tabs.Root value={showRegister ? "register" : "login"} class="w-full">
          <Tabs.List
            class="grid w-full grid-cols-2 mb-6 bg-secondary rounded-full p-1"
          >
            <Tabs.Trigger
              value="login"
              onclick={() => {
                showRegister = false;
                errorMessage = "";
              }}
              class="rounded-full data-[state=active]:bg-card data-[state=active]:shadow-sm"
              >{m.auth_login()}</Tabs.Trigger
            >
            <Tabs.Trigger
              value="register"
              onclick={() => {
                showRegister = true;
                errorMessage = "";
              }}
              class="rounded-full data-[state=active]:bg-card data-[state=active]:shadow-sm"
              >{m.auth_register()}</Tabs.Trigger
            >
          </Tabs.List>

          <Tabs.Content value="login">
            {@render loginForm()}
          </Tabs.Content>

          <Tabs.Content value="register">
            {@render registerForm(m.auth_register())}
          </Tabs.Content>
        </Tabs.Root>
      {:else}
        {@render loginForm()}
      {/if}
    </div>

    {#if isNative()}
      <!-- Locked out (dead server, forgotten password, offline)? The
           downloaded books are always one tap away — this is what makes
           an accidental logout harmless. -->
      <div class="mt-4 text-center">
        <Button
          variant="ghost"
          class="text-sm text-muted-foreground"
          onclick={() => switchAppMode("local")}
        >
          {m.mode_use_local()}
        </Button>
      </div>
    {/if}
  </div>
</div>
