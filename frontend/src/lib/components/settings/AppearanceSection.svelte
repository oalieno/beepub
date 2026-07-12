<script lang="ts">
  import { ChevronRight, Sun, Moon, Monitor } from "@lucide/svelte";
  import * as m from "$lib/paraglide/messages.js";
  import {
    themePreference,
    setThemePreference,
    type ThemePreference,
  } from "$lib/stores/theme";

  let show = $state(false);
  const themeOptions: {
    value: ThemePreference;
    label: () => string;
    icon: typeof Sun;
  }[] = [
    { value: "system", label: m.profile_theme_system, icon: Monitor },
    { value: "light", label: m.profile_theme_light, icon: Sun },
    { value: "dark", label: m.profile_theme_dark, icon: Moon },
  ];
  let themeLabel = $derived(
    themeOptions.find((o) => o.value === $themePreference)?.label() ?? "",
  );
</script>

<button
  class="flex items-center gap-3 px-4 py-3.5 w-full text-left hover:bg-secondary/50 transition-colors"
  onclick={() => (show = !show)}
>
  {#if $themePreference === "dark"}
    <Moon size={20} class="text-muted-foreground shrink-0" />
  {:else if $themePreference === "light"}
    <Sun size={20} class="text-muted-foreground shrink-0" />
  {:else}
    <Monitor size={20} class="text-muted-foreground shrink-0" />
  {/if}
  <span class="text-sm font-medium flex-1">{m.profile_appearance()}</span>
  <span class="text-sm text-muted-foreground">{themeLabel}</span>
  <ChevronRight
    size={16}
    class="text-muted-foreground/50 transition-transform {show
      ? 'rotate-90'
      : ''}"
  />
</button>
{#if show}
  <div class="px-4 py-3 space-y-1">
    {#each themeOptions as option}
      {@const active = $themePreference === option.value}
      <button
        class="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm transition-colors {active
          ? 'bg-primary/10 text-primary font-medium'
          : 'text-foreground hover:bg-secondary/50'}"
        onclick={() => setThemePreference(option.value)}
      >
        <option.icon size={16} class="shrink-0" />
        <span class="flex-1 text-left">{option.label()}</span>
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
