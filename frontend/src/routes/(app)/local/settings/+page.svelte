<script lang="ts">
  import { goto } from "$app/navigation";
  import { ChevronRight, RefreshCw, Rss, Server } from "@lucide/svelte";
  import KosyncSettingsDialog from "$lib/components/KosyncSettingsDialog.svelte";
  import LanguageSection from "$lib/components/settings/LanguageSection.svelte";
  import AppearanceSection from "$lib/components/settings/AppearanceSection.svelte";
  import * as m from "$lib/paraglide/messages.js";

  let kosyncOpen = $state(false);
</script>

<svelte:head>
  <title>{m.local_settings_page_title()}</title>
</svelte:head>

<div class="max-w-5xl mx-auto px-6 sm:px-8 py-6">
  <!-- Language & appearance -->
  <div class="bg-card card-soft rounded-2xl overflow-hidden mb-4">
    <LanguageSection />

    <!-- Divider -->
    <div class="flex justify-center">
      <div class="w-4/5 h-px bg-border" style="transform: scaleY(0.5);"></div>
    </div>

    <AppearanceSection />
  </div>

  <!-- Sync & catalogs -->
  <div class="bg-card card-soft rounded-2xl overflow-hidden mb-4">
    <button
      class="flex items-center gap-3 px-4 py-3.5 w-full text-left hover:bg-secondary/50 transition-colors"
      onclick={() => (kosyncOpen = true)}
    >
      <RefreshCw size={20} class="text-muted-foreground shrink-0" />
      <span class="text-sm font-medium flex-1">{m.kosync_title()}</span>
      <ChevronRight size={16} class="text-muted-foreground/50" />
    </button>

    <!-- Divider -->
    <div class="flex justify-center">
      <div class="w-4/5 h-px bg-border" style="transform: scaleY(0.5);"></div>
    </div>

    <button
      class="flex items-center gap-3 px-4 py-3.5 w-full text-left hover:bg-secondary/50 transition-colors"
      onclick={() => goto("/catalogs")}
    >
      <Rss size={20} class="text-muted-foreground shrink-0" />
      <span class="text-sm font-medium flex-1">{m.nav_catalogs()}</span>
      <ChevronRight size={16} class="text-muted-foreground/50" />
    </button>
  </div>

  <!-- Connect a server -->
  <div class="bg-card card-soft rounded-2xl overflow-hidden">
    <button
      class="flex items-center gap-3 px-4 py-3.5 w-full text-left hover:bg-secondary/50 transition-colors"
      onclick={() => goto("/setup")}
    >
      <Server size={20} class="text-muted-foreground shrink-0" />
      <span class="text-sm font-medium flex-1">{m.local_connect_server()}</span>
      <ChevronRight size={16} class="text-muted-foreground/50" />
    </button>
  </div>
</div>

<KosyncSettingsDialog bind:open={kosyncOpen} />
