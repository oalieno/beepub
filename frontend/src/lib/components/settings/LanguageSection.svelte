<script lang="ts">
  import { ChevronRight, Globe } from "@lucide/svelte";
  import * as m from "$lib/paraglide/messages.js";
  import { getLocale, setLocale, locales } from "$lib/paraglide/runtime.js";

  let show = $state(false);
</script>

<button
  class="flex items-center gap-3 px-4 py-3.5 w-full text-left hover:bg-secondary/50 transition-colors"
  onclick={() => (show = !show)}
>
  <Globe size={20} class="text-muted-foreground shrink-0" />
  <span class="text-sm font-medium flex-1">{m.profile_language()}</span>
  <span class="text-sm text-muted-foreground"
    >{getLocale() === "en" ? "English" : "繁體中文"}</span
  >
  <ChevronRight
    size={16}
    class="text-muted-foreground/50 transition-transform {show
      ? 'rotate-90'
      : ''}"
  />
</button>
{#if show}
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
