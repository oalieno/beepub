<script lang="ts">
  import { onMount } from "svelte";
  import { adminApi } from "$lib/api/bookshelves";
  import { toastStore } from "$lib/stores/toast";
  import type { AdminSettings } from "$lib/types";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Button } from "$lib/components/ui/button";
  import * as Card from "$lib/components/ui/card";
  import * as Select from "$lib/components/ui/select";
  import { Save } from "@lucide/svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { FormSkeleton } from "$lib/components/skeletons";

  let settings = $state<AdminSettings | null>(null);
  let loading = $state(true);
  let saving = $state(false);
  // Form state
  let timezone = $state("Asia/Taipei");
  let metadataEnabled = $state(true);
  let metadataHour = $state(3);
  let metadataIntervalDays = $state(7);
  let metadataCooldownDays = $state(30);

  // Provider credentials (stored once)
  let geminiApiKey = $state("");
  let openaiApiKey = $state("");
  let openaiBaseUrl = $state("");

  // Per-feature config
  let companionProvider = $state("");
  let companionModel = $state("");
  let tagProvider = $state("");
  let tagModel = $state("");
  let imageProvider = $state("");
  let imageModel = $state("");
  let embeddingProvider = $state("");
  let embeddingModel = $state("");
  let embeddingApiUrl = $state("");
  let embeddingApiKey = $state("");

  // Derived: which providers have credentials configured
  let hasGemini = $derived(geminiApiKey.trim().length > 0);
  let hasOpenai = $derived(openaiBaseUrl.trim().length > 0);

  // Model lists fetched from providers
  let modelCache = $state<
    Record<string, { models: { id: string; name: string }[]; loading: boolean }>
  >({
    gemini: { models: [], loading: false },
    openai: { models: [], loading: false },
  });

  async function fetchModels(provider: "gemini" | "openai") {
    modelCache[provider].loading = true;
    try {
      modelCache[provider].models = await adminApi.getAiModels(provider);
    } catch {
      modelCache[provider].models = [];
    } finally {
      modelCache[provider].loading = false;
    }
  }

  function getModelsForProvider(
    provider: string,
  ): { id: string; name: string }[] {
    return modelCache[provider]?.models ?? [];
  }

  function isLoadingModels(provider: string): boolean {
    return modelCache[provider]?.loading ?? false;
  }

  const allTimezones = Intl.supportedValuesOf("timeZone");

  function formatUtcOffset(timeZone: string): string {
    try {
      const parts = new Intl.DateTimeFormat("en-US", {
        timeZone,
        timeZoneName: "shortOffset",
        hour: "2-digit",
      }).formatToParts(new Date());

      const rawOffset =
        parts.find((part) => part.type === "timeZoneName")?.value ?? "GMT+0";
      const match = rawOffset.match(/GMT([+-])(\d{1,2})(?::?(\d{2}))?/i);

      if (!match) return "UTC+00:00";

      const sign = match[1];
      const hour = String(parseInt(match[2], 10)).padStart(2, "0");
      const minute = String(parseInt(match[3] ?? "0", 10)).padStart(2, "0");

      return `UTC${sign}${hour}:${minute}`;
    } catch {
      return "UTC+00:00";
    }
  }

  function getUtcOffsetMinutes(timeZone: string): number {
    const offset = formatUtcOffset(timeZone);
    const match = offset.match(/UTC([+-])(\d{2}):(\d{2})/);
    if (!match) return 0;

    const sign = match[1] === "+" ? 1 : -1;
    const hour = parseInt(match[2], 10);
    const minute = parseInt(match[3], 10);
    return sign * (hour * 60 + minute);
  }

  const timezoneOptions = allTimezones
    .map((tz) => ({
      value: tz,
      label: `${tz} (${formatUtcOffset(tz)})`,
      offsetMinutes: getUtcOffsetMinutes(tz),
    }))
    .sort(
      (a, b) =>
        a.offsetMinutes - b.offsetMinutes || a.label.localeCompare(b.label),
    );

  function getTimezoneLabel(timeZone: string): string {
    return (
      timezoneOptions.find((option) => option.value === timeZone)?.label ??
      `${timeZone} (UTC+00:00)`
    );
  }

  const hourOptions = Array.from({ length: 24 }, (_, i) => ({
    value: String(i),
    label: `${String(i).padStart(2, "0")}:00`,
  }));

  function providerLabel(value: string): string {
    if (value === "gemini") return "Gemini";
    if (value === "openai") return "OpenAI Compatible";
    return "Not configured";
  }

  onMount(async () => {
    await loadSettings();
  });

  async function loadSettings() {
    loading = true;
    try {
      settings = await adminApi.getSettings();
      timezone = settings.timezone;
      metadataEnabled = settings.metadata_refresh_enabled === "true";
      metadataHour = parseInt(settings.metadata_refresh_hour) || 3;
      metadataIntervalDays =
        parseInt(settings.metadata_refresh_interval_days) || 7;
      metadataCooldownDays =
        parseInt(settings.metadata_refresh_cooldown_days) || 30;
      geminiApiKey = settings.gemini_api_key || "";
      openaiApiKey = settings.openai_api_key || "";
      openaiBaseUrl = settings.openai_base_url || "";
      companionProvider = settings.companion_provider || "";
      companionModel = settings.companion_model || "";
      tagProvider = settings.tag_provider || "";
      tagModel = settings.tag_model || "";
      imageProvider = settings.image_provider || "";
      imageModel = settings.image_model || "";
      embeddingProvider = settings.embedding_provider || "";
      embeddingModel = settings.embedding_model || "";
      embeddingApiUrl = settings.embedding_api_url || "";
      embeddingApiKey = settings.embedding_api_key || "";

      // Fetch model lists for configured providers
      const fetches: Promise<void>[] = [];
      if (geminiApiKey.trim()) fetches.push(fetchModels("gemini"));
      if (openaiBaseUrl.trim()) fetches.push(fetchModels("openai"));
      await Promise.all(fetches);
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function handleSave() {
    saving = true;
    try {
      settings = await adminApi.updateSettings({
        timezone,
        metadata_refresh_enabled: metadataEnabled ? "true" : "false",
        metadata_refresh_hour: String(metadataHour),
        metadata_refresh_interval_days: String(metadataIntervalDays),
        metadata_refresh_cooldown_days: String(metadataCooldownDays),
        gemini_api_key: geminiApiKey,
        openai_api_key: openaiApiKey,
        openai_base_url: openaiBaseUrl,
        companion_provider: companionProvider,
        companion_model: companionModel,
        tag_provider: tagProvider,
        tag_model: tagModel,
        image_provider: imageProvider,
        image_model: imageModel,
        embedding_provider: embeddingProvider,
        embedding_model: embeddingModel,
        embedding_api_url: embeddingApiUrl,
        embedding_api_key: embeddingApiKey,
      });
      toastStore.success("Settings saved");
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      saving = false;
    }
  }
</script>

{#snippet featureProviderFields(
  prefix: string,
  value: string,
  model: string,
  modelPlaceholder: string,
  onChange: (v: string) => void,
  onModelChange: (v: string) => void,
)}
  <div class="grid grid-cols-1 sm:grid-cols-2 gap-5">
    <div class="space-y-1.5">
      <Label for="{prefix}-provider">Provider</Label>
      <Select.Root
        type="single"
        value={value || "none"}
        onValueChange={(v) => onChange(v === "none" ? "" : v)}
      >
        <Select.Trigger id="{prefix}-provider" class="w-full bg-background">
          {providerLabel(value)}
        </Select.Trigger>
        <Select.Content align="start">
          <Select.Item value="none">Not configured</Select.Item>
          {#if hasGemini}
            <Select.Item value="gemini">Gemini</Select.Item>
          {/if}
          {#if hasOpenai}
            <Select.Item value="openai">OpenAI Compatible</Select.Item>
          {/if}
        </Select.Content>
      </Select.Root>
      {#if !hasGemini && !hasOpenai}
        <p class="text-xs text-muted-foreground">
          Add API keys in the AI Providers section above first
        </p>
      {/if}
    </div>
    {#if value}
      {@const models = getModelsForProvider(value)}
      {@const loadingM = isLoadingModels(value)}
      <div class="space-y-1.5">
        <Label for="{prefix}-model">Model</Label>
        {#if loadingM}
          <div
            class="flex items-center gap-2 h-9 px-3 text-sm text-muted-foreground"
          >
            <Spinner size="sm" />
            Loading models…
          </div>
        {:else if models.length > 0}
          <Select.Root
            type="single"
            value={model || "none"}
            onValueChange={(v) => onModelChange(v === "none" ? "" : v)}
          >
            <Select.Trigger id="{prefix}-model" class="w-full bg-background">
              {model || "Select a model"}
            </Select.Trigger>
            <Select.Content align="start" class="max-h-64">
              <Select.Item value="none">Select a model</Select.Item>
              {#each models as m}
                <Select.Item value={m.id}>{m.name}</Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>
        {:else}
          <Input
            id="{prefix}-model"
            placeholder={modelPlaceholder}
            value={model}
            oninput={(e) => onModelChange(e.currentTarget.value)}
          />
          <p class="text-xs text-muted-foreground">
            Could not load models — type a model name manually
          </p>
        {/if}
      </div>
    {/if}
  </div>
{/snippet}

<svelte:head>
  <title>Settings - Admin - BeePub</title>
</svelte:head>

<div class="max-w-5xl mx-auto px-6 sm:px-8 py-6">
  <div class="mb-8">
    <a
      href="/admin"
      class="text-muted-foreground hover:text-foreground text-sm mb-1 inline-block"
      >&larr; Admin</a
    >
    <h1 class="text-3xl font-bold text-foreground">Settings</h1>
    <p class="text-muted-foreground mt-1">Configure application settings</p>
  </div>

  {#if loading}
    <FormSkeleton cards={6} />
  {:else}
    <div class="space-y-6">
      <!-- Timezone -->
      <Card.Root>
        <Card.Header>
          <Card.Title>Timezone</Card.Title>
          <Card.Description
            >Used for reading activity tracking and scheduled tasks</Card.Description
          >
        </Card.Header>
        <Card.Content>
          <div class="max-w-sm space-y-1.5">
            <Label for="timezone">Application timezone</Label>
            <Select.Root
              type="single"
              value={timezone}
              onValueChange={(v) => (timezone = v)}
            >
              <Select.Trigger id="timezone" class="w-full bg-background">
                {getTimezoneLabel(timezone)}
              </Select.Trigger>
              <Select.Content align="start" class="max-h-64">
                {#each timezoneOptions as option}
                  <Select.Item value={option.value}>{option.label}</Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
          </div>
        </Card.Content>
      </Card.Root>

      <!-- Metadata Refresh -->
      <Card.Root>
        <Card.Header>
          <Card.Title>Metadata Auto-Refresh</Card.Title>
          <Card.Description
            >Automatically fetch book metadata from Goodreads and Readmoo</Card.Description
          >
        </Card.Header>
        <Card.Content class="space-y-5">
          <label class="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              bind:checked={metadataEnabled}
              class="h-4 w-4 rounded border-border text-primary focus:ring-primary/50"
            />
            <span class="text-sm text-foreground"
              >Enable automatic metadata refresh</span
            >
          </label>

          {#if metadataEnabled}
            <div
              class="grid grid-cols-1 sm:grid-cols-3 gap-5 pt-4 border-t border-border/30"
            >
              <div class="space-y-1.5">
                <Label for="metadata-hour">Run at hour</Label>
                <Select.Root
                  type="single"
                  value={String(metadataHour)}
                  onValueChange={(v) => (metadataHour = parseInt(v))}
                >
                  <Select.Trigger
                    id="metadata-hour"
                    class="w-full bg-background"
                  >
                    {String(metadataHour).padStart(2, "0")}:00
                  </Select.Trigger>
                  <Select.Content align="start" class="max-h-64">
                    {#each hourOptions as opt}
                      <Select.Item value={opt.value}>{opt.label}</Select.Item>
                    {/each}
                  </Select.Content>
                </Select.Root>
                <p class="text-xs text-muted-foreground">
                  Hour of day ({timezone})
                </p>
              </div>
              <div class="space-y-1.5">
                <Label for="metadata-interval">Schedule interval</Label>
                <div class="flex items-center gap-2">
                  <Input
                    id="metadata-interval"
                    type="number"
                    min={1}
                    max={365}
                    bind:value={metadataIntervalDays}
                  />
                  <span class="text-sm text-muted-foreground shrink-0"
                    >days</span
                  >
                </div>
                <p class="text-xs text-muted-foreground">
                  How often to run the refresh
                </p>
              </div>
              <div class="space-y-1.5">
                <Label for="metadata-cooldown">Cooldown</Label>
                <div class="flex items-center gap-2">
                  <Input
                    id="metadata-cooldown"
                    type="number"
                    min={1}
                    max={365}
                    bind:value={metadataCooldownDays}
                  />
                  <span class="text-sm text-muted-foreground shrink-0"
                    >days</span
                  >
                </div>
                <p class="text-xs text-muted-foreground">
                  Skip books fetched within this period
                </p>
              </div>
            </div>
          {/if}
        </Card.Content>
      </Card.Root>

      <!-- AI Providers -->
      <Card.Root>
        <Card.Header>
          <Card.Title>AI Providers</Card.Title>
          <Card.Description>
            Configure API keys for AI providers. Each feature below can use any
            configured provider.
          </Card.Description>
        </Card.Header>
        <Card.Content class="space-y-5">
          <div class="max-w-sm space-y-1.5">
            <Label for="gemini-key">Gemini API Key</Label>
            <Input
              id="gemini-key"
              type="password"
              placeholder="AIza..."
              value={geminiApiKey}
              oninput={(e) => (geminiApiKey = e.currentTarget.value)}
            />
          </div>
          <div class="border-t border-border/30 pt-5">
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-5">
              <div class="space-y-1.5">
                <Label for="openai-key">OpenAI Compatible API Key</Label>
                <Input
                  id="openai-key"
                  type="password"
                  placeholder="sk-... (optional for Ollama)"
                  value={openaiApiKey}
                  oninput={(e) => (openaiApiKey = e.currentTarget.value)}
                />
              </div>
              <div class="space-y-1.5">
                <Label for="openai-url">Base URL</Label>
                <Input
                  id="openai-url"
                  placeholder="https://api.openai.com/v1"
                  value={openaiBaseUrl}
                  oninput={(e) => (openaiBaseUrl = e.currentTarget.value)}
                />
                <p class="text-xs text-muted-foreground">
                  For Ollama: http://host:11434/v1
                </p>
              </div>
            </div>
          </div>
        </Card.Content>
      </Card.Root>

      <!-- Companion AI -->
      <Card.Root>
        <Card.Header>
          <Card.Title>Companion AI</Card.Title>
          <Card.Description>
            For the AI Reading Companion chat sidebar
          </Card.Description>
        </Card.Header>
        <Card.Content>
          {@render featureProviderFields(
            "companion",
            companionProvider,
            companionModel,
            "gemini-2.5-flash",
            (v) => (companionProvider = v),
            (v) => (companionModel = v),
          )}
        </Card.Content>
      </Card.Root>

      <!-- Tag AI -->
      <Card.Root>
        <Card.Header>
          <Card.Title>Tag AI</Card.Title>
          <Card.Description>
            For AI-powered book tagging and recommendations
          </Card.Description>
        </Card.Header>
        <Card.Content>
          {@render featureProviderFields(
            "tag",
            tagProvider,
            tagModel,
            "gemini-2.0-flash",
            (v) => (tagProvider = v),
            (v) => (tagModel = v),
          )}
        </Card.Content>
      </Card.Root>

      <!-- Image AI -->
      <Card.Root>
        <Card.Header>
          <Card.Title>Image AI</Card.Title>
          <Card.Description>
            For AI Illustrations (requires Gemini with image generation support)
          </Card.Description>
        </Card.Header>
        <Card.Content>
          {@render featureProviderFields(
            "image",
            imageProvider,
            imageModel,
            "gemini-2.0-flash-exp",
            (v) => (imageProvider = v),
            (v) => (imageModel = v),
          )}
        </Card.Content>
      </Card.Root>

      <!-- Embedding AI -->
      <Card.Root>
        <Card.Header>
          <Card.Title>Embedding AI</Card.Title>
          <Card.Description>
            For semantic search and similar book recommendations. Connects to
            any OpenAI-compatible embedding API (LM Studio, Ollama, etc).
          </Card.Description>
        </Card.Header>
        <Card.Content class="space-y-5">
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <div class="space-y-1.5">
              <Label for="embedding-api-url">API Base URL</Label>
              <Input
                id="embedding-api-url"
                placeholder="http://localhost:1234/v1"
                value={embeddingApiUrl}
                oninput={(e) => (embeddingApiUrl = e.currentTarget.value)}
              />
              <p class="text-xs text-muted-foreground">
                OpenAI-compatible /v1/embeddings endpoint
              </p>
            </div>
            <div class="space-y-1.5">
              <Label for="embedding-model">Model</Label>
              <Input
                id="embedding-model"
                placeholder="text-embedding-qwen3-embedding-0.6b"
                value={embeddingModel}
                oninput={(e) => (embeddingModel = e.currentTarget.value)}
              />
            </div>
          </div>
          <div class="max-w-sm space-y-1.5">
            <Label for="embedding-api-key">API Key</Label>
            <Input
              id="embedding-api-key"
              type="password"
              placeholder="Optional — not needed for local servers"
              value={embeddingApiKey}
              oninput={(e) => (embeddingApiKey = e.currentTarget.value)}
            />
          </div>
        </Card.Content>
      </Card.Root>

      <!-- Save -->
      <div class="flex justify-end">
        <Button disabled={saving} class="rounded-xl" onclick={handleSave}>
          <Save size={16} />
          {saving ? "Saving..." : "Save Settings"}
        </Button>
      </div>
    </div>
  {/if}
</div>
