<script lang="ts">
  import { onMount } from "svelte";
  import { adminApi } from "$lib/api/admin";
  import { toastStore } from "$lib/stores/toast";
  import type { AdminSettings } from "$lib/types";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Button } from "$lib/components/ui/button";
  import * as Card from "$lib/components/ui/card";
  import * as Select from "$lib/components/ui/select";
  import { Eye, EyeOff, Save } from "@lucide/svelte";
  import Spinner from "$lib/components/Spinner.svelte";
  import { FormSkeleton } from "$lib/components/skeletons";
  import BackButton from "$lib/components/BackButton.svelte";
  import * as m from "$lib/paraglide/messages.js";

  let settings = $state<AdminSettings | null>(null);
  let loading = $state(true);
  let saving = $state(false);
  // Form state
  let registrationEnabled = $state(false);
  let timezone = $state("Asia/Taipei");

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

  // External metadata API keys
  let googleBooksApiKey = $state("");
  let hardcoverApiToken = $state("");

  // Password visibility toggles
  let visibleFields = $state<Record<string, boolean>>({});

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

  function providerLabel(value: string): string {
    if (value === "gemini") return m.admin_settings_provider_gemini();
    if (value === "openai") return m.admin_settings_provider_openai();
    return m.admin_settings_not_configured();
  }

  onMount(async () => {
    await loadSettings();
  });

  async function loadSettings() {
    loading = true;
    try {
      settings = await adminApi.getSettings();
      registrationEnabled = settings.registration_enabled === "true";
      timezone = settings.timezone;
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
      googleBooksApiKey = settings.google_books_api_key || "";
      hardcoverApiToken = settings.hardcover_api_token || "";

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

  function isValidUrl(url: string): boolean {
    const trimmed = url.trim();
    return trimmed === "" || /^https?:\/\//.test(trimmed);
  }

  let openaiBaseUrlError = $derived(
    openaiBaseUrl.trim() && !isValidUrl(openaiBaseUrl)
      ? m.admin_settings_url_validation()
      : "",
  );
  let embeddingApiUrlError = $derived(
    embeddingApiUrl.trim() && !isValidUrl(embeddingApiUrl)
      ? m.admin_settings_url_validation()
      : "",
  );

  async function handleSave() {
    if (openaiBaseUrlError) {
      document.getElementById("openai-url")?.focus();
      return;
    }
    if (embeddingApiUrlError) {
      document.getElementById("embedding-api-url")?.focus();
      return;
    }
    saving = true;
    try {
      settings = await adminApi.updateSettings({
        registration_enabled: registrationEnabled ? "true" : "false",
        timezone,
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
        google_books_api_key: googleBooksApiKey,
        hardcover_api_token: hardcoverApiToken,
      });
      toastStore.success("Settings saved");
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
          <Select.Item value="none"
            >{m.admin_settings_not_configured()}</Select.Item
          >
          {#if hasGemini}
            <Select.Item value="gemini"
              >{m.admin_settings_provider_gemini()}</Select.Item
            >
          {/if}
          {#if hasOpenai}
            <Select.Item value="openai"
              >{m.admin_settings_provider_openai()}</Select.Item
            >
          {/if}
        </Select.Content>
      </Select.Root>
      {#if !hasGemini && !hasOpenai}
        <p class="text-xs text-muted-foreground">
          {m.admin_settings_api_keys_help()}
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
            {m.admin_settings_loading_models()}
          </div>
        {:else if models.length > 0}
          <Select.Root
            type="single"
            value={model || "none"}
            onValueChange={(v) => onModelChange(v === "none" ? "" : v)}
          >
            <Select.Trigger id="{prefix}-model" class="w-full bg-background">
              {model || m.admin_settings_select_model()}
            </Select.Trigger>
            <Select.Content align="start" class="max-h-64">
              <Select.Item value="none"
                >{m.admin_settings_select_model()}</Select.Item
              >
              {#each models as mdl}
                <Select.Item value={mdl.id}>{mdl.name}</Select.Item>
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
            {m.admin_settings_model_load_error()}
          </p>
        {/if}
      </div>
    {/if}
  </div>
{/snippet}

<svelte:head>
  <title>{m.admin_settings_title()}</title>
</svelte:head>

<div class="max-w-5xl mx-auto px-6 sm:px-8 py-6">
  <div class="mb-8">
    <div class="mb-1">
      <BackButton href="/admin" label={m.nav_admin()} />
    </div>
    <h1 class="text-3xl font-bold text-foreground">
      {m.admin_settings_heading()}
    </h1>
    <p class="text-muted-foreground mt-1">{m.admin_settings_subtitle()}</p>
  </div>

  {#if loading}
    <FormSkeleton cards={6} />
  {:else}
    <div class="space-y-6">
      <!-- User Registration -->
      <Card.Root>
        <Card.Header>
          <Card.Title>{m.admin_settings_registration()}</Card.Title>
          <Card.Description
            >{m.admin_settings_registration_desc()}</Card.Description
          >
        </Card.Header>
        <Card.Content>
          <label class="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              bind:checked={registrationEnabled}
              class="h-4 w-4 rounded border-border text-primary focus:ring-primary/50"
            />
            <span class="text-sm text-foreground"
              >{m.admin_settings_registration_label()}</span
            >
          </label>
          <p class="text-xs text-muted-foreground mt-2">
            {m.admin_settings_registration_help()}
          </p>
        </Card.Content>
      </Card.Root>

      <!-- Timezone -->
      <Card.Root>
        <Card.Header>
          <Card.Title>{m.admin_settings_timezone()}</Card.Title>
          <Card.Description>{m.admin_settings_timezone_desc()}</Card.Description
          >
        </Card.Header>
        <Card.Content>
          <div class="max-w-sm space-y-1.5">
            <Label for="timezone">{m.admin_settings_timezone_label()}</Label>
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

      <!-- External Metadata APIs -->
      <Card.Root>
        <Card.Header>
          <Card.Title>{m.admin_settings_external_apis()}</Card.Title>
          <Card.Description>
            {m.admin_settings_external_apis_desc()}
          </Card.Description>
        </Card.Header>
        <Card.Content class="space-y-5">
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <div class="space-y-1.5">
              <Label for="google-books-key"
                >{m.admin_settings_google_books()}</Label
              >
              {@render passwordInput(
                "google-books-key",
                "AIza...",
                googleBooksApiKey,
                (v) => (googleBooksApiKey = v),
              )}
              <p class="text-xs text-muted-foreground">
                {m.admin_settings_google_books_help()}
              </p>
            </div>
            <div class="space-y-1.5">
              <Label for="hardcover-token">{m.admin_settings_hardcover()}</Label
              >
              {@render passwordInput(
                "hardcover-token",
                m.admin_settings_hardcover_placeholder(),
                hardcoverApiToken,
                (v) => (hardcoverApiToken = v),
              )}
              <p class="text-xs text-muted-foreground">
                {m.admin_settings_hardcover_help()}
              </p>
            </div>
          </div>
        </Card.Content>
      </Card.Root>

      <!-- AI Providers -->
      <Card.Root>
        <Card.Header>
          <Card.Title>{m.admin_settings_ai_providers()}</Card.Title>
          <Card.Description>
            {m.admin_settings_ai_providers_desc()}
          </Card.Description>
        </Card.Header>
        <Card.Content class="space-y-5">
          <div class="max-w-sm space-y-1.5">
            <Label for="gemini-key">{m.admin_settings_gemini()}</Label>
            {@render passwordInput(
              "gemini-key",
              "AIza...",
              geminiApiKey,
              (v) => (geminiApiKey = v),
            )}
          </div>
          <div class="border-t border-border/30 pt-5">
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-5">
              <div class="space-y-1.5">
                <Label for="openai-key">{m.admin_settings_openai_key()}</Label>
                {@render passwordInput(
                  "openai-key",
                  m.admin_settings_openai_key_placeholder(),
                  openaiApiKey,
                  (v) => (openaiApiKey = v),
                )}
              </div>
              <div class="space-y-1.5">
                <Label for="openai-url">{m.admin_settings_base_url()}</Label>
                <Input
                  id="openai-url"
                  placeholder="https://api.openai.com/v1"
                  value={openaiBaseUrl}
                  oninput={(e) => (openaiBaseUrl = e.currentTarget.value)}
                />
                {#if openaiBaseUrlError}
                  <p class="text-xs text-red-600">{openaiBaseUrlError}</p>
                {:else}
                  <p class="text-xs text-muted-foreground">
                    {m.admin_settings_openai_url_help()}
                  </p>
                {/if}
              </div>
            </div>
          </div>
        </Card.Content>
      </Card.Root>

      <!-- Companion AI -->
      <Card.Root>
        <Card.Header>
          <Card.Title>{m.admin_settings_companion()}</Card.Title>
          <Card.Description>
            {m.admin_settings_companion_desc()}
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
          <Card.Title>{m.admin_settings_tag()}</Card.Title>
          <Card.Description>
            {m.admin_settings_tag_desc()}
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
          <Card.Title>{m.admin_settings_image()}</Card.Title>
          <Card.Description>
            {m.admin_settings_image_desc()}
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
          <Card.Title>{m.admin_settings_embedding()}</Card.Title>
          <Card.Description>
            {m.admin_settings_embedding_desc()}
          </Card.Description>
        </Card.Header>
        <Card.Content class="space-y-5">
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <div class="space-y-1.5">
              <Label for="embedding-api-url"
                >{m.admin_settings_embedding_url()}</Label
              >
              <Input
                id="embedding-api-url"
                placeholder="http://localhost:1234/v1"
                value={embeddingApiUrl}
                oninput={(e) => (embeddingApiUrl = e.currentTarget.value)}
              />
              {#if embeddingApiUrlError}
                <p class="text-xs text-red-600">{embeddingApiUrlError}</p>
              {:else}
                <p class="text-xs text-muted-foreground">
                  {m.admin_settings_embedding_url_help()}
                </p>
              {/if}
            </div>
            <div class="space-y-1.5">
              <Label for="embedding-model"
                >{m.admin_settings_embedding_model()}</Label
              >
              <Input
                id="embedding-model"
                placeholder="text-embedding-qwen3-embedding-0.6b"
                value={embeddingModel}
                oninput={(e) => (embeddingModel = e.currentTarget.value)}
              />
            </div>
          </div>
          <div class="max-w-sm space-y-1.5">
            <Label for="embedding-api-key"
              >{m.admin_settings_embedding_key()}</Label
            >
            {@render passwordInput(
              "embedding-api-key",
              m.admin_settings_embedding_key_placeholder(),
              embeddingApiKey,
              (v) => (embeddingApiKey = v),
            )}
          </div>
        </Card.Content>
      </Card.Root>

      <!-- Save -->
      <div class="flex justify-end">
        <Button disabled={saving} class="rounded-xl" onclick={handleSave}>
          <Save size={16} />
          {saving ? m.admin_settings_saving() : m.admin_settings_save()}
        </Button>
      </div>
    </div>
  {/if}
</div>
