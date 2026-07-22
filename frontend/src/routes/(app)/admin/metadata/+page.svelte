<script lang="ts">
  import { onMount } from "svelte";
  import { adminApi } from "$lib/api/admin";
  import { metadataApi } from "$lib/api/metadata";
  import { invalidateMetadataSources } from "$lib/stores/metadataSources";
  import { toastStore } from "$lib/stores/toast";
  import type { MetadataSourceOut, MetadataSourceStats } from "$lib/types";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Button } from "$lib/components/ui/button";
  import { Badge } from "$lib/components/ui/badge";
  import * as Card from "$lib/components/ui/card";
  import * as Collapsible from "$lib/components/ui/collapsible";
  import * as Tooltip from "$lib/components/ui/tooltip";
  import { Switch } from "$lib/components/ui/switch";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import {
    BookText,
    ChevronDown,
    ExternalLink,
    Eye,
    EyeOff,
    Image as ImageIcon,
    MessageSquareText,
    Star,
    Tags as TagsIcon,
  } from "@lucide/svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { FormSkeleton } from "$lib/components/skeletons";
  import BackButton from "$lib/components/BackButton.svelte";
  import * as m from "$lib/paraglide/messages.js";

  let sources = $state<MetadataSourceOut[]>([]);
  let stats = $state<Record<string, MetadataSourceStats>>({});
  let loading = $state(true);

  // Control state, keyed by plugin name / setting key. Everything on
  // this page applies instantly — only credential edits stage until
  // their own per-source save.
  let enabled = $state<Record<string, boolean>>({});
  let inJob = $state<Record<string, boolean>>({});
  let keyValues = $state<Record<string, string>>({});
  let keyDirty = $state<Record<string, boolean>>({});
  let keySaving = $state<Record<string, boolean>>({});
  let visibleFields = $state<Record<string, boolean>>({});
  let openRows = $state<Record<string, boolean>>({});

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

  // The five-slot capability fingerprint: fixed order so the icons line
  // up into comparable columns across rows.
  const FINGERPRINT = [
    {
      icon: BookText,
      label: m.metadata_provides_bibliographic,
      test: (p: string[]) => BIBLIO_FIELDS.some((f) => p.includes(f)),
    },
    {
      icon: ImageIcon,
      label: m.metadata_provides_cover,
      test: (p: string[]) => p.includes("cover_url"),
    },
    {
      icon: Star,
      label: m.metadata_provides_ratings,
      test: (p: string[]) => RATING_FIELDS.some((f) => p.includes(f)),
    },
    {
      icon: MessageSquareText,
      label: m.metadata_provides_reviews,
      test: (p: string[]) => p.includes("reviews"),
    },
    {
      icon: TagsIcon,
      label: m.metadata_provides_tags,
      test: (p: string[]) => p.includes("tags"),
    },
  ];

  const FIELD_LABELS: Record<string, () => string> = {
    title: m.source_field_title,
    authors: m.source_field_authors,
    publisher: m.source_field_publisher,
    description: m.source_field_description,
    published_date: m.source_field_published_date,
    language: m.source_field_language,
    cover_url: m.source_field_cover_url,
    rating: m.source_field_rating,
    rating_count: m.source_field_rating_count,
    readers_count: m.source_field_readers_count,
    reviews: m.source_field_reviews,
    tags: m.source_field_tags,
  };

  function sublabel(source: MetadataSourceOut): string {
    const parts: string[] = [
      source.kind === "api" ? m.source_kind_api() : m.source_kind_scraper(),
    ];
    if (source.locale) parts.push(source.locale);
    const searchable = source.accepts.filter((c) => c !== "url");
    if (searchable.length === 1) {
      parts.push(
        searchable[0] === "isbn" ? m.source_isbn_only() : m.source_title_only(),
      );
    }
    return parts.join(" · ");
  }

  function acceptsChips(source: MetadataSourceOut): string[] {
    const chips: string[] = [];
    if (source.accepts.includes("isbn")) chips.push(m.metadata_accepts_isbn());
    if (source.accepts.includes("title")) {
      chips.push(m.metadata_accepts_title());
    }
    if (source.accepts.includes("url")) chips.push(m.source_accepts_url());
    return chips;
  }

  function missingKey(source: MetadataSourceOut): boolean {
    return (
      source.setting_keys.length > 0 &&
      !source.setting_keys.every((key) => (keyValues[key] ?? "").trim())
    );
  }

  function relTime(isoString: string | null): string {
    if (!isoString) return "—";
    const diffMin = Math.floor(
      (Date.now() - new Date(isoString).getTime()) / 60000,
    );
    if (diffMin < 1) return m.admin_calibre_just_now();
    if (diffMin < 60) {
      return m.admin_calibre_minutes_ago({ minutes: String(diffMin) });
    }
    const diffHours = Math.floor(diffMin / 60);
    if (diffHours < 24) {
      return m.admin_calibre_hours_ago({ hours: String(diffHours) });
    }
    return m.admin_calibre_days_ago({
      days: String(Math.floor(diffHours / 24)),
    });
  }

  function applySettings(settings: Record<string, string>) {
    const jobRaw = (settings.metadata_job_sources ?? "").trim();
    for (const source of sources) {
      enabled[source.name] =
        settings[`metadata_source_${source.name}_enabled`] !== "false";
      // "" = every source (the default), "-" = none, else explicit list.
      inJob[source.name] =
        jobRaw === ""
          ? true
          : jobRaw === "-"
            ? false
            : jobRaw
                .split(",")
                .map((name) => name.trim())
                .includes(source.name);
      for (const key of source.setting_keys) {
        keyValues[key] = settings[key] ?? "";
      }
      keyDirty[source.name] = false;
    }
  }

  onMount(async () => {
    try {
      const [registry, settings, statsOut] = await Promise.all([
        metadataApi.getSources(),
        adminApi.getSettings(),
        metadataApi.getSourceStats(),
      ]);
      sources = registry.sources;
      stats = statsOut.stats;
      applySettings(settings);
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  });

  async function persistEnabled(name: string, value: boolean) {
    try {
      await adminApi.updateSettings({
        [`metadata_source_${name}_enabled`]: value ? "true" : "false",
      });
      invalidateMetadataSources();
    } catch (e) {
      enabled[name] = !value;
      toastStore.error((e as Error).message);
    }
  }

  function jobListValue(): string {
    const checked = sources.filter((s) => inJob[s.name]).map((s) => s.name);
    if (checked.length === 0) return "-";
    if (checked.length === sources.length) return "";
    return checked.join(",");
  }

  // metadata_job_sources is one shared setting — serialize the writes so
  // two quick taps can't land out of order.
  let jobChain: Promise<unknown> = Promise.resolve();
  function persistJob(name: string, value: boolean) {
    jobChain = jobChain
      .then(() =>
        adminApi.updateSettings({ metadata_job_sources: jobListValue() }),
      )
      .then(() => invalidateMetadataSources())
      .catch((e) => {
        inJob[name] = !value;
        toastStore.error((e as Error).message);
      });
  }

  async function saveKeys(source: MetadataSourceOut) {
    if (keySaving[source.name]) return;
    keySaving[source.name] = true;
    try {
      const payload: Record<string, string> = {};
      for (const key of source.setting_keys) {
        payload[key] = keyValues[key] ?? "";
      }
      const settings = await adminApi.updateSettings(payload);
      // Re-read: the server masks the stored secret, and `configured`
      // on the registry may have flipped.
      const registry = await metadataApi.getSources();
      sources = registry.sources;
      for (const key of source.setting_keys) {
        keyValues[key] = settings[key] ?? "";
      }
      keyDirty[source.name] = false;
      invalidateMetadataSources();
      toastStore.success(m.admin_settings_saved());
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      keySaving[source.name] = false;
    }
  }
</script>

<svelte:head>
  <title>{m.admin_metadata_title()} - BeePub</title>
</svelte:head>

<div class="max-w-5xl mx-auto px-4 sm:px-6 py-6 sm:py-10 pb-24">
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
    <Tooltip.Provider delayDuration={150}>
      <Card.Root class="overflow-hidden py-0">
        <Card.Content class="p-0">
          <div
            class="flex items-center gap-2 border-b border-border px-4 py-2.5 text-xs text-muted-foreground sm:gap-3 sm:px-6"
          >
            <div class="min-w-0 flex-1"></div>
            <div class="hidden w-28 sm:block"></div>
            <div class="w-12 text-center">{m.admin_metadata_enabled()}</div>
            <div class="w-12 text-center">{m.source_col_auto()}</div>
            <div class="w-8"></div>
          </div>

          <div class="divide-y divide-border">
            {#each sources as source (source.name)}
              {@const stat = stats[source.name]}
              {@const isOn = enabled[source.name]}
              <Collapsible.Root
                open={openRows[source.name] ?? false}
                onOpenChange={(value) => (openRows[source.name] = value)}
              >
                <div
                  class="flex items-center gap-2 px-4 py-3.5 sm:gap-3 sm:px-6"
                >
                  <div
                    class="min-w-0 flex-1 transition-opacity {isOn
                      ? ''
                      : 'opacity-50'}"
                  >
                    <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span class="font-medium text-foreground">
                        {source.label}
                      </span>
                      {#if missingKey(source)}
                        <Badge
                          variant="outline"
                          class="border-primary/40 font-normal text-primary"
                        >
                          {m.admin_metadata_needs_key()}
                        </Badge>
                      {/if}
                      {#if stat?.cooldown_seconds}
                        {@const cooldownMin = Math.max(
                          1,
                          Math.ceil(stat.cooldown_seconds / 60),
                        )}
                        <Badge variant="outline" class="font-normal">
                          {cooldownMin >= 120
                            ? m.source_badge_cooldown_hours({
                                hours: String(Math.round(cooldownMin / 60)),
                              })
                            : m.source_badge_cooldown({
                                minutes: String(cooldownMin),
                              })}
                        </Badge>
                      {/if}
                      {#if (stat?.consecutive_failures ?? 0) >= 3}
                        <Badge
                          variant="outline"
                          class="border-destructive/40 font-normal text-destructive"
                        >
                          {m.source_badge_failing({
                            count: String(stat.consecutive_failures),
                          })}
                        </Badge>
                      {/if}
                    </div>
                    <p class="mt-0.5 text-xs text-muted-foreground">
                      {sublabel(source)}
                    </p>
                  </div>

                  <div
                    class="hidden w-28 items-center justify-between transition-opacity sm:flex {isOn
                      ? ''
                      : 'opacity-50'}"
                  >
                    {#each FINGERPRINT as slot (slot.label)}
                      {@const Icon = slot.icon}
                      {@const has = slot.test(source.provides)}
                      <Tooltip.Root>
                        <Tooltip.Trigger class="cursor-default">
                          <Icon
                            size={15}
                            class={has
                              ? "text-foreground/70"
                              : "text-muted-foreground/25"}
                          />
                        </Tooltip.Trigger>
                        <Tooltip.Content>{slot.label()}</Tooltip.Content>
                      </Tooltip.Root>
                    {/each}
                  </div>

                  <div class="flex w-12 justify-center">
                    <Switch
                      bind:checked={enabled[source.name]}
                      onCheckedChange={(value) =>
                        persistEnabled(source.name, value)}
                      aria-label={`${m.admin_metadata_enabled()} ${source.label}`}
                    />
                  </div>
                  <div class="flex w-12 justify-center">
                    <Checkbox
                      bind:checked={inJob[source.name]}
                      onCheckedChange={(value) =>
                        persistJob(source.name, value === true)}
                      disabled={!isOn}
                      aria-label={`${m.source_col_auto()} ${source.label}`}
                    />
                  </div>
                  <Collapsible.Trigger
                    class="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                    aria-label={source.label}
                  >
                    <ChevronDown
                      size={16}
                      class="transition-transform {openRows[source.name]
                        ? 'rotate-180'
                        : ''}"
                    />
                  </Collapsible.Trigger>
                </div>

                <Collapsible.Content>
                  <div class="space-y-3 px-4 pb-5 pt-0.5 sm:px-6">
                    <div class="flex flex-wrap items-center gap-1.5 text-sm">
                      <span
                        class="w-full text-xs text-muted-foreground sm:w-20"
                      >
                        {m.source_provides_label()}
                      </span>
                      {#each source.provides as field (field)}
                        <Badge variant="outline" class="font-normal">
                          {FIELD_LABELS[field]?.() ?? field}
                        </Badge>
                      {/each}
                    </div>

                    <div class="flex flex-wrap items-center gap-1.5 text-sm">
                      <span
                        class="w-full text-xs text-muted-foreground sm:w-20"
                      >
                        {m.source_accepts_label()}
                      </span>
                      {#each acceptsChips(source) as chip (chip)}
                        <Badge variant="outline" class="font-normal">
                          {chip}
                        </Badge>
                      {/each}
                    </div>

                    <div class="space-y-1 text-xs text-muted-foreground">
                      <p>
                        {stat?.last_fetched_at
                          ? m.source_stats_last_fetched({
                              time: relTime(stat.last_fetched_at),
                            })
                          : m.source_stats_never()}
                        {#if stat && (stat.books_found > 0 || stat.books_not_found > 0)}
                          · {m.source_stats_found({
                            count: String(stat.books_found),
                          })} · {m.source_stats_not_found({
                            count: String(stat.books_not_found),
                          })}
                        {/if}
                      </p>
                      {#if stat?.last_error}
                        <p class="text-destructive/90">
                          {m.source_stats_last_error({
                            time: relTime(stat.last_error_at),
                          })}: {stat.last_error}
                        </p>
                      {/if}
                      {#if stat?.last_ratelimited_at}
                        <p>
                          {m.source_stats_last_ratelimited({
                            time: relTime(stat.last_ratelimited_at),
                          })}
                        </p>
                      {/if}
                    </div>

                    {#if source.setting_keys.length > 0}
                      <div
                        class="max-w-sm space-y-3 border-t border-border/40 pt-3"
                      >
                        {#each source.setting_keys as key (key)}
                          {@const info = SETTING_LABELS[key]}
                          <div class="space-y-1.5">
                            <Label for={`plugin-${key}`}>
                              {info ? info.label() : key}
                            </Label>
                            <div class="flex items-center gap-2">
                              <div class="relative flex-1">
                                <Input
                                  id={`plugin-${key}`}
                                  type={visibleFields[key]
                                    ? "text"
                                    : "password"}
                                  placeholder={info?.placeholder ?? ""}
                                  value={keyValues[key] ?? ""}
                                  oninput={(e) => {
                                    keyValues[key] = e.currentTarget.value;
                                    keyDirty[source.name] = true;
                                  }}
                                  class={keyDirty[source.name] ? "pr-10" : ""}
                                />
                                {#if keyDirty[source.name]}
                                  <button
                                    aria-label={m.common_toggle_password()}
                                    type="button"
                                    class="absolute right-0 top-0 h-full px-3 text-muted-foreground transition-colors hover:text-foreground"
                                    onclick={() =>
                                      (visibleFields[key] =
                                        !visibleFields[key])}
                                    tabindex={-1}
                                  >
                                    {#if visibleFields[key]}
                                      <EyeOff size={16} />
                                    {:else}
                                      <Eye size={16} />
                                    {/if}
                                  </button>
                                {/if}
                              </div>
                              <Button
                                size="sm"
                                variant="outline"
                                disabled={!keyDirty[source.name] ||
                                  keySaving[source.name]}
                                onclick={() => saveKeys(source)}
                              >
                                {#if keySaving[source.name]}
                                  <Spinner size="sm" />
                                {:else}
                                  {m.common_save()}
                                {/if}
                              </Button>
                            </div>
                            <p class="text-xs text-muted-foreground">
                              {#if !keyDirty[source.name] && (keyValues[key] ?? "").trim()}
                                {m.source_key_saved()}
                              {:else if info?.help}
                                {info.help()}
                              {/if}
                              {#if source.key_url}
                                <a
                                  href={source.key_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  class="inline-flex items-center gap-0.5 text-primary hover:underline"
                                >
                                  {m.source_get_key()}
                                  <ExternalLink size={11} />
                                </a>
                              {/if}
                            </p>
                          </div>
                        {/each}
                      </div>
                    {/if}
                  </div>
                </Collapsible.Content>
              </Collapsible.Root>
            {/each}
          </div>
        </Card.Content>
      </Card.Root>
    </Tooltip.Provider>
  {/if}
</div>
