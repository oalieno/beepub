<script lang="ts">
  import { goto } from "$app/navigation";
  import {
    getServerUrl,
    hasServerUrl,
    isLocalMode,
    switchAppMode,
  } from "$lib/api/client";
  import * as m from "$lib/paraglide/messages.js";
  import { isNative } from "$lib/platform";
  import { ArrowLeft, Check, Server, Smartphone } from "@lucide/svelte";
  import { Button } from "$lib/components/ui/button";

  // Modes are a native concept — web is served by the server it uses.
  if (typeof window !== "undefined" && !isNative()) {
    void goto("/", { replaceState: true });
  }

  // One-time reads — switching always goes through a full page load.
  const localMode = isLocalMode();
  const serverUrl = hasServerUrl() ? getServerUrl() : "";

  function goBack() {
    // Entered via the in-app switcher button: pop, don't push. Direct
    // loads (cold-start restore) fall back to the mode's home.
    if (history.length > 1) {
      history.back();
    } else {
      goto(localMode ? "/local" : "/", { replaceState: true });
    }
  }
</script>

<svelte:head>
  <title>{m.mode_switch_title()}</title>
</svelte:head>

<div
  class="min-h-screen flex items-center justify-center px-4"
  style="padding-top: env(safe-area-inset-top, 0px); padding-bottom: env(safe-area-inset-bottom, 0px);"
>
  <div class="w-full max-w-sm">
    <h1
      class="text-2xl font-bold text-center mb-2"
      style="font-family: var(--font-heading)"
    >
      {m.mode_switch_title()}
    </h1>
    <p class="text-sm text-muted-foreground text-center mb-8">
      {m.mode_switch_subtitle()}
    </p>

    <div class="space-y-3">
      {#if serverUrl}
        <button
          class="w-full bg-card card-soft rounded-2xl p-5 flex items-center gap-4 text-left transition-colors {localMode
            ? 'hover:bg-secondary/50'
            : 'ring-2 ring-primary'}"
          disabled={!localMode}
          aria-current={!localMode}
          onclick={() => switchAppMode("server")}
        >
          <div
            class="w-11 h-11 rounded-xl bg-primary/10 flex items-center justify-center shrink-0"
          >
            <Server size={22} class="text-primary" />
          </div>
          <div class="flex-1 min-w-0">
            <p class="font-semibold">{m.mode_server_label()}</p>
            <p class="text-sm text-muted-foreground truncate">{serverUrl}</p>
          </div>
          {#if !localMode}
            <Check size={20} class="text-primary shrink-0" />
          {/if}
        </button>
      {:else}
        <button
          class="w-full bg-card card-soft rounded-2xl p-5 flex items-center gap-4 text-left transition-colors hover:bg-secondary/50"
          onclick={() => goto("/setup")}
        >
          <div
            class="w-11 h-11 rounded-xl bg-muted flex items-center justify-center shrink-0"
          >
            <Server size={22} class="text-muted-foreground" />
          </div>
          <div class="flex-1 min-w-0">
            <p class="font-semibold">{m.mode_server_label()}</p>
            <p class="text-sm text-muted-foreground">{m.auth_no_server()}</p>
          </div>
        </button>
      {/if}

      <button
        class="w-full bg-card card-soft rounded-2xl p-5 flex items-center gap-4 text-left transition-colors {localMode
          ? 'ring-2 ring-primary'
          : 'hover:bg-secondary/50'}"
        disabled={localMode}
        aria-current={localMode}
        onclick={() => switchAppMode("local")}
      >
        <div
          class="w-11 h-11 rounded-xl bg-primary/10 flex items-center justify-center shrink-0"
        >
          <Smartphone size={22} class="text-primary" />
        </div>
        <div class="flex-1 min-w-0">
          <p class="font-semibold">{m.mode_local_label()}</p>
          <p class="text-sm text-muted-foreground">{m.mode_local_desc()}</p>
        </div>
        {#if localMode}
          <Check size={20} class="text-primary shrink-0" />
        {/if}
      </button>
    </div>

    <div class="mt-6 text-center">
      {#if serverUrl}
        <Button
          variant="ghost"
          class="text-sm text-muted-foreground"
          onclick={() => goto("/setup")}
        >
          {m.mode_change_server()}
        </Button>
      {/if}
      <div>
        <Button
          variant="ghost"
          class="text-sm text-muted-foreground"
          onclick={goBack}
        >
          <ArrowLeft size={16} />
          {m.common_back()}
        </Button>
      </div>
    </div>
  </div>
</div>
