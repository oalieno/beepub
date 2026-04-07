<script lang="ts">
  import { goto } from "$app/navigation";
  import { authStore } from "$lib/stores/auth";
  import { authApi } from "$lib/api/auth";
  import { isNative } from "$lib/platform";
  import { isOnline } from "$lib/services/network";
  import { toastStore } from "$lib/stores/toast";
  import { UserRole } from "$lib/types";
  import {
    BookOpen,
    BookCopy,
    ShelvingUnit,
    Highlighter,
    Settings,
    Download,
    Dices,
    LogOut,
    ChevronRight,
    KeyRound,
    Eye,
    EyeOff,
  } from "@lucide/svelte";
  import * as Avatar from "$lib/components/ui/avatar";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Button } from "$lib/components/ui/button";
  import * as m from "$lib/paraglide/messages.js";
  import { getLocale, setLocale, locales } from "$lib/paraglide/runtime.js";
  import { Globe } from "@lucide/svelte";

  let isAdmin = $derived($authStore.user?.role === UserRole.Admin);
  let online = $derived($isOnline);

  // Language
  let showLanguage = $state(false);

  // Change password
  let showChangePassword = $state(false);
  let currentPassword = $state("");
  let newPassword = $state("");
  let confirmPassword = $state("");
  let changingPassword = $state(false);
  let showCurrentPw = $state(false);
  let showNewPw = $state(false);
  let passwordError = $state("");

  function handleDisabledClick(e: Event) {
    e.preventDefault();
    toastStore.info(m.nav_available_when_online());
  }

  async function logout() {
    await authStore.logout();
    goto("/login");
  }

  async function handleChangePassword() {
    passwordError = "";
    if (newPassword !== confirmPassword) {
      passwordError = m.profile_password_mismatch();
      return;
    }
    changingPassword = true;
    try {
      await authApi.changePassword(currentPassword, newPassword);
      toastStore.success(m.profile_password_changed());
      showChangePassword = false;
      currentPassword = "";
      newPassword = "";
      confirmPassword = "";
    } catch (e) {
      passwordError = (e as Error).message;
    } finally {
      changingPassword = false;
    }
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
      label: m.nav_my_books(),
      icon: BookOpen,
      requiresOnline: true,
    },
    {
      href: "/all-books",
      label: m.nav_all_books(),
      icon: BookCopy,
      requiresOnline: true,
    },
    {
      href: "/highlights",
      label: m.nav_highlights(),
      icon: Highlighter,
      requiresOnline: true,
    },
    {
      href: "/bookshelves",
      label: m.nav_shelves(),
      icon: ShelvingUnit,
      requiresOnline: true,
    },
    ...(isNative()
      ? [
          {
            href: "/downloads",
            label: m.nav_downloads(),
            icon: Download,
            requiresOnline: false,
          } satisfies ProfileLink,
        ]
      : []),
    { href: "/gacha", label: m.nav_gacha(), icon: Dices, requiresOnline: true },
    ...(isAdmin
      ? [
          {
            href: "/admin",
            label: m.nav_admin(),
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

  <!-- Language & Password settings -->
  <div class="bg-card card-soft rounded-2xl overflow-hidden mb-4">
    <!-- Language -->
    <button
      class="flex items-center gap-3 px-4 py-3.5 w-full text-left hover:bg-secondary/50 transition-colors"
      onclick={() => (showLanguage = !showLanguage)}
    >
      <Globe size={20} class="text-muted-foreground shrink-0" />
      <span class="text-sm font-medium flex-1">{m.profile_language()}</span>
      <span class="text-sm text-muted-foreground"
        >{getLocale() === "en" ? "English" : "繁體中文"}</span
      >
      <ChevronRight
        size={16}
        class="text-muted-foreground/50 transition-transform {showLanguage
          ? 'rotate-90'
          : ''}"
      />
    </button>
    {#if showLanguage}
      <div class="px-4 py-3 space-y-1">
        {#each locales as locale}
          {@const active = getLocale() === locale}
          <button
            class="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm transition-colors {active
              ? 'bg-primary/10 text-primary font-medium'
              : 'text-foreground hover:bg-secondary/50'}"
            onclick={() => {
              setLocale(locale);
            }}
          >
            <span class="flex-1 text-left"
              >{locale === "en" ? "English" : "繁體中文"}</span
            >
            {#if active}
              <svg
                class="w-4 h-4 text-primary"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                stroke-width="2.5"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  d="M5 13l4 4L19 7"
                />
              </svg>
            {/if}
          </button>
        {/each}
      </div>
    {/if}

    <!-- Divider -->
    <div class="flex justify-center">
      <div class="w-4/5 h-px bg-border" style="transform: scaleY(0.5);"></div>
    </div>

    <!-- Change Password -->
    <button
      class="flex items-center gap-3 px-4 py-3.5 w-full text-left hover:bg-secondary/50 transition-colors"
      onclick={() => {
        showChangePassword = !showChangePassword;
        passwordError = "";
      }}
    >
      <KeyRound size={20} class="text-muted-foreground shrink-0" />
      <span class="text-sm font-medium flex-1"
        >{m.profile_change_password()}</span
      >
      <ChevronRight
        size={16}
        class="text-muted-foreground/50 transition-transform {showChangePassword
          ? 'rotate-90'
          : ''}"
      />
    </button>
    {#if showChangePassword}
      <form
        onsubmit={(e) => {
          e.preventDefault();
          handleChangePassword();
        }}
        class="px-4 py-4 space-y-3"
      >
        <div class="space-y-1.5">
          <Label for="current-pw" class="text-sm"
            >{m.profile_current_password()}</Label
          >
          <div class="relative">
            <Input
              id="current-pw"
              type={showCurrentPw ? "text" : "password"}
              bind:value={currentPassword}
              placeholder={m.profile_current_password_placeholder()}
              required
              class="pr-10"
            />
            <button
              type="button"
              class="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:text-foreground transition-colors"
              onclick={() => (showCurrentPw = !showCurrentPw)}
              tabindex={-1}
            >
              {#if showCurrentPw}
                <EyeOff size={16} />
              {:else}
                <Eye size={16} />
              {/if}
            </button>
          </div>
        </div>
        <div class="space-y-1.5">
          <Label for="new-pw" class="text-sm">{m.profile_new_password()}</Label>
          <div class="relative">
            <Input
              id="new-pw"
              type={showNewPw ? "text" : "password"}
              bind:value={newPassword}
              placeholder={m.profile_new_password_placeholder()}
              required
              class="pr-10"
            />
            <button
              type="button"
              class="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:text-foreground transition-colors"
              onclick={() => (showNewPw = !showNewPw)}
              tabindex={-1}
            >
              {#if showNewPw}
                <EyeOff size={16} />
              {:else}
                <Eye size={16} />
              {/if}
            </button>
          </div>
        </div>
        <div class="space-y-1.5">
          <Label for="confirm-pw" class="text-sm"
            >{m.profile_confirm_password()}</Label
          >
          <Input
            id="confirm-pw"
            type="password"
            bind:value={confirmPassword}
            placeholder={m.profile_confirm_password_placeholder()}
            required
          />
        </div>
        {#if passwordError}
          <p class="text-sm text-red-600">{passwordError}</p>
        {/if}
        <Button
          type="submit"
          disabled={changingPassword}
          class="rounded-xl text-sm"
        >
          {changingPassword
            ? m.profile_changing()
            : m.profile_change_password()}
        </Button>
      </form>
    {/if}
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
        <span class="text-sm font-medium flex-1">{m.nav_admin()}</span>
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
      <span class="text-sm font-medium">{m.profile_logout()}</span>
    </button>
  </div>
</div>
