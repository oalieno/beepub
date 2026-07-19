<script lang="ts">
  import { onMount } from "svelte";
  import { adminApi } from "$lib/api/admin";
  import { metadataApi } from "$lib/api/metadata";
  import { invalidateMetadataSources } from "$lib/stores/metadataSources";
  import { toastStore } from "$lib/stores/toast";
  import type { MetadataSourceOut } from "$lib/types";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Button } from "$lib/components/ui/button";
  import { Badge } from "$lib/components/ui/badge";
  import * as Card from "$lib/components/ui/card";
  import { Switch } from "$lib/components/ui/switch";
  import { Eye, EyeOff, Save } from "@lucide/svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { FormSkeleton } from "$lib/components/skeletons";
  import BackButton from "$lib/components/BackButton.svelte";
  import * as m from "$lib/paraglide/messages.js";

  let sources = $state<MetadataSourceOut[]>([]);
  let loading = $state(true);
  let saving = $state(false);

  // Form state, keyed by plugin name / setting key
  let enabled = $state<Record<string, boolean>>({});
  let inJob = $state<Record<string, boolean>>({});
  let keyValues = $state<Record<string, string>>({});
  let visibleFields = $state<Record<string, boolean>>({});

  // The background-fetch section only offers enabled sources — the job
  // is enabled ∩ list server-side, a disabled source can't be fetched.
  const enabledSources = $derived(sources.filter((s) => enabled[s.name]));

  // Labels for the credential inputs of the built-in plugins; a drop-in
  // plugin's keys fall back to the raw key name.
  const SETTING_LABELS: Record<
    string,
    { label: () => string; placeholder: string; help?: () => string }
  > = {
    google_books_api_key: {
      label: m.admin_settings_google_books,
      placeholder: "AIza...",
      help: m.admin_settings_google_books_help,
    },
    hardcover_api_token: {
      label: m.admin_settings_hardcover,
      placeholder: m.admin_settings_hardcover_placeholder(),
      help: m.admin_settings_hardcover_help,
    },
  };

  const BIBLIO_FIELDS = [
    "title",
    "authors",
    "publisher",
    "description",
    "published_date",
    "language",
  ];
  const RATING_FIELDS = ["rating", "rating_count", "readers_count"];

  function providesChips(source: MetadataSourceOut): string[] {
    const chips: string[] = [];
    if (source.provides.some((f) => BIBLIO_FIELDS.includes(f))) {
      chips.push(m.metadata_provides_bibliographic());
    }
    if (source.provides.includes("cover_url")) {
      chips.push(m.metadata_provides_cover());
    }
    if (source.provides.some((f) => RATING_FIELDS.includes(f))) {
      chips.push(m.metadata_provides_ratings());
    }
    if (source.provides.includes("reviews")) {
      chips.push(m.metadata_provides_reviews());
    }
    if (source.provides.includes("tags")) {
      chips.push(m.metadata_provides_tags());
    }
    return chips;
  }

  function acceptsChips(source: MetadataSourceOut): string[] {
    const chips: string[] = [];
    if (source.accepts.includes("isbn")) chips.push(m.metadata_accepts_isbn());
    if (source.accepts.includes("title")) {
      chips.push(m.metadata_accepts_title());
    }
    return chips;
  }

  function missingKey(source: MetadataSourceOut): boolean {
    return (
      source.setting_keys.length > 0 &&
      !source.setting_keys.every((key) => (keyValues[key] ?? "").trim())
    );
  }

  onMount(async () => {
    try {
      const [registry, settings] = await Promise.all([
        metadataApi.getSources(),
        adminApi.getSettings(),
      ]);
      sources = registry.sources;

      const jobRaw = (settings.metadata_job_sources ?? "").trim();
      const jobList = jobRaw
        ? new Set(
            jobRaw
              .split(",")
              .map((name) => name.trim())
              .filter(Boolean),
          )
        : null; // empty setting = every enabled source

      for (const source of sources) {
        enabled[source.name] =
          settings[`metadata_source_${source.name}_enabled`] !== "false";
        inJob[source.name] = jobList ? jobList.has(source.name) : true;
        for (const key of source.setting_keys) {
          keyValues[key] = settings[key] ?? "";
        }
      }
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  });

  async function handleSave() {
    if (saving) return;
    saving = true;
    try {
      const payload: Record<string, string> = {};
      for (const source of sources) {
        payload[`metadata_source_${source.name}_enabled`] = enabled[source.name]
          ? "true"
          : "false";
        for (const key of source.setting_keys) {
          // Masked secrets round-trip untouched = "unchanged" server-side.
          payload[key] = keyValues[key] ?? "";
        }
      }
      // Empty = "all enabled sources" (the default): store the explicit
      // list only when the operator actually excluded something.
      const checked = enabledSources
        .filter((source) => inJob[source.name])
        .map((source) => source.name);
      payload.metadata_job_sources =
        checked.length === enabledSources.length ? "" : checked.join(",");

      await adminApi.updateSettings(payload);
      invalidateMetadataSources();
      toastStore.success(m.admin_settings_saved());
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      saving = false;
    }
  }
</script>

{#snippet passwordInput(
  id: string,
  placeholder: string,
  value: string,
  onChange: (v: string) => void,
)}
  <div class="relative">
    <Input
      {id}
      type={visibleFields[id] ? "text" : "password"}
      {placeholder}
      {value}
      oninput={(e) => onChange(e.currentTarget.value)}
      class="pr-10"
    />
    <button
      aria-label={m.common_toggle_password()}
      type="button"
      class="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:text-foreground transition-colors"
      onclick={() => (visibleFields[id] = !visibleFields[id])}
      tabindex={-1}
    >
      {#if visibleFields[id]}
        <EyeOff size={16} />
      {:else}
        <Eye size={16} />
      {/if}
    </button>
  </div>
{/snippet}

<svelte:head>
  <title>{m.admin_metadata_title()} - BeePub</title>
</svelte:head>

<div class="max-w-3xl mx-auto px-4 sm:px-6 py-6 sm:py-10 pb-24">
  <BackButton href="/admin" label={m.nav_admin()} />

  <div class="mt-4 mb-6">
    <h1 class="text-2xl font-bold text-foreground">
      {m.admin_metadata_title()}
    </h1>
    <p class="mt-1 text-sm text-muted-foreground">
      {m.admin_metadata_subtitle()}
    </p>
  </div>

  {#if loading}
    <FormSkeleton />
  {:else}
    <Card.Root>
      <Card.Content class="divide-y divide-border p-0">
        {#each sources as source (source.name)}
          <div
            class="space-y-3 px-6 py-5 transition-opacity {enabled[source.name]
              ? ''
              : 'opacity-55'}"
          >
            <div class="flex items-center justify-between gap-3">
              <div class="flex flex-wrap items-center gap-2">
                <span class="font-medium text-foreground">{source.label}</span>
                <Badge variant="outline">
                  {source.kind === "api"
                    ? m.source_kind_api()
                    : m.source_kind_scraper()}
                </Badge>
                {#if source.locale}
                  <Badge variant="outline">{source.locale}</Badge>
                {/if}
                {#if missingKey(source)}
                  <Badge variant="secondary">
                    {m.admin_metadata_needs_key()}
                  </Badge>
                {/if}
              </div>
              <label class="flex shrink-0 items-center gap-2 text-sm">
                <span class="text-muted-foreground">
                  {m.admin_metadata_enabled()}
                </span>
                <Switch bind:checked={enabled[source.name]} />
              </label>
            </div>

            <div class="flex flex-wrap items-center gap-1.5">
              {#each acceptsChips(source) as chip}
                <Badge variant="secondary" class="font-normal">{chip}</Badge>
              {/each}
              <span class="mx-1 text-muted-foreground/50">→</span>
              {#each providesChips(source) as chip}
                <Badge variant="outline" class="font-normal">{chip}</Badge>
              {/each}
            </div>

            {#if source.setting_keys.length > 0}
              <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
                {#each source.setting_keys as key (key)}
                  {@const info = SETTING_LABELS[key]}
                  <div class="space-y-1.5">
                    <Label for={`plugin-${key}`}>
                      {info ? info.label() : key}
                    </Label>
                    {@render passwordInput(
                      `plugin-${key}`,
                      info?.placeholder ?? "",
                      keyValues[key] ?? "",
                      (v) => (keyValues[key] = v),
                    )}
                    {#if info?.help}
                      <p class="text-xs text-muted-foreground">{info.help()}</p>
                    {/if}
                  </div>
                {/each}
              </div>
            {/if}
          </div>
        {/each}
      </Card.Content>
    </Card.Root>

    <!-- Background fetch is the job's setting, not a per-plugin one:
         which enabled sources the library-wide batch pulls from. -->
    <div class="mt-8 mb-3">
      <h2 class="text-lg font-semibold text-foreground">
        {m.admin_metadata_in_job()}
      </h2>
      <p class="mt-1 text-sm text-muted-foreground">
        {m.admin_metadata_in_job_help()}
      </p>
    </div>
    <Card.Root>
      <Card.Content class="p-6">
        {#if enabledSources.length > 0}
          <div class="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {#each enabledSources as source (source.name)}
              <label class="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  bind:checked={inJob[source.name]}
                  class="h-4 w-4 rounded border-input accent-primary"
                />
                <span>{source.label}</span>
              </label>
            {/each}
          </div>
        {:else}
          <p class="text-sm text-muted-foreground">
            {m.admin_metadata_in_job_empty()}
          </p>
        {/if}
      </Card.Content>
    </Card.Root>

    <div class="mt-6 flex justify-end">
      <Button onclick={handleSave} disabled={saving}>
        {#if saving}
          <Spinner size="sm" />
        {:else}
          <Save size={16} />
        {/if}
        {m.common_save()}
      </Button>
    </div>
  {/if}
</div>
