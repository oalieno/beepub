<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { authStore } from "$lib/stores/auth";
  import { adminApi } from "$lib/api/bookshelves";
  import { toastStore } from "$lib/stores/toast";
  import type { AdminSettings } from "$lib/types";
  import { UserRole } from "$lib/types";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Button } from "$lib/components/ui/button";
  import * as Card from "$lib/components/ui/card";
  import * as Select from "$lib/components/ui/select";
  import { Save } from "@lucide/svelte";
  import Spinner from "$lib/components/Spinner.svelte";

  let settings = $state<AdminSettings | null>(null);
  let loading = $state(true);
  let saving = $state(false);

  // Form state
  let timezone = $state("Asia/Taipei");
  let metadataEnabled = $state(true);
  let metadataHour = $state(3);
  let metadataIntervalDays = $state(7);
  let metadataCooldownDays = $state(30);

  // LLM settings
  let llmProvider = $state("");
  let geminiApiKey = $state("");
  let geminiModel = $state("");
  let openaiApiKey = $state("");
  let openaiBaseUrl = $state("");
  let openaiModel = $state("");

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

  onMount(async () => {
    if (!$authStore.user || $authStore.user.role !== UserRole.Admin) {
      goto("/");
      return;
    }
    await loadSettings();
  });

  async function loadSettings() {
    loading = true;
    try {
      settings = await adminApi.getSettings($authStore.token!);
      timezone = settings.timezone;
      metadataEnabled = settings.metadata_refresh_enabled === "true";
      metadataHour = parseInt(settings.metadata_refresh_hour) || 3;
      metadataIntervalDays =
        parseInt(settings.metadata_refresh_interval_days) || 7;
      metadataCooldownDays =
        parseInt(settings.metadata_refresh_cooldown_days) || 30;
      llmProvider = settings.llm_provider || "";
      geminiApiKey = settings.gemini_api_key || "";
      geminiModel = settings.gemini_model || "";
      openaiApiKey = settings.openai_api_key || "";
      openaiBaseUrl = settings.openai_base_url || "";
      openaiModel = settings.openai_model || "";
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function handleSave() {
    if (!$authStore.token) return;
    saving = true;
    try {
      settings = await adminApi.updateSettings(
        {
          timezone,
          metadata_refresh_enabled: metadataEnabled ? "true" : "false",
          metadata_refresh_hour: String(metadataHour),
          metadata_refresh_interval_days: String(metadataIntervalDays),
          metadata_refresh_cooldown_days: String(metadataCooldownDays),
          llm_provider: llmProvider,
          gemini_api_key: geminiApiKey,
          gemini_model: geminiModel,
          openai_api_key: openaiApiKey,
          openai_base_url: openaiBaseUrl,
          openai_model: openaiModel,
        },
        $authStore.token,
      );
      toastStore.success("Settings saved");
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      saving = false;
    }
  }
</script>

<svelte:head>
  <title>Settings - Admin - BeePub</title>
</svelte:head>

<div class="max-w-6xl mx-auto px-4 sm:px-6 py-6">
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
    <div class="flex items-center justify-center h-40">
      <Spinner size="lg" />
    </div>
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
          <!-- Enable/Disable -->
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
              <!-- Hour -->
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

              <!-- Interval -->
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

              <!-- Cooldown -->
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

      <!-- LLM Provider -->
      <Card.Root>
        <Card.Header>
          <Card.Title>AI / LLM Provider</Card.Title>
          <Card.Description>
            Configure the AI model for Reading Companion and other AI features.
            Leave blank to use .env defaults.
          </Card.Description>
        </Card.Header>
        <Card.Content class="space-y-5">
          <div class="max-w-sm space-y-1.5">
            <Label for="llm-provider">Provider</Label>
            <Select.Root
              type="single"
              value={llmProvider || "default"}
              onValueChange={(v) => (llmProvider = v === "default" ? "" : v)}
            >
              <Select.Trigger id="llm-provider" class="w-full bg-background">
                {llmProvider === "gemini"
                  ? "Gemini"
                  : llmProvider === "openai"
                    ? "OpenAI Compatible"
                    : "Default (from .env)"}
              </Select.Trigger>
              <Select.Content align="start">
                <Select.Item value="default">Default (from .env)</Select.Item>
                <Select.Item value="gemini">Gemini</Select.Item>
                <Select.Item value="openai">OpenAI Compatible</Select.Item>
              </Select.Content>
            </Select.Root>
          </div>

          {#if llmProvider === "gemini"}
            <div
              class="grid grid-cols-1 sm:grid-cols-2 gap-5 pt-4 border-t border-border/30"
            >
              <div class="space-y-1.5">
                <Label for="gemini-key">API Key</Label>
                <Input
                  id="gemini-key"
                  type="password"
                  placeholder="AIza..."
                  bind:value={geminiApiKey}
                />
              </div>
              <div class="space-y-1.5">
                <Label for="gemini-model">Model</Label>
                <Input
                  id="gemini-model"
                  placeholder="gemini-2.0-flash-exp"
                  bind:value={geminiModel}
                />
              </div>
            </div>
          {/if}

          {#if llmProvider === "openai"}
            <div
              class="grid grid-cols-1 sm:grid-cols-2 gap-5 pt-4 border-t border-border/30"
            >
              <div class="space-y-1.5">
                <Label for="openai-key">API Key</Label>
                <Input
                  id="openai-key"
                  type="password"
                  placeholder="sk-..."
                  bind:value={openaiApiKey}
                />
                <p class="text-xs text-muted-foreground">
                  Leave blank if not required (e.g. local Ollama)
                </p>
              </div>
              <div class="space-y-1.5">
                <Label for="openai-model">Model</Label>
                <Input
                  id="openai-model"
                  placeholder="gpt-4o-mini"
                  bind:value={openaiModel}
                />
              </div>
              <div class="space-y-1.5 sm:col-span-2">
                <Label for="openai-url">Base URL</Label>
                <Input
                  id="openai-url"
                  placeholder="https://api.openai.com/v1"
                  bind:value={openaiBaseUrl}
                />
                <p class="text-xs text-muted-foreground">
                  For Ollama: http://host:11434/v1 · For any OpenAI-compatible
                  API
                </p>
              </div>
            </div>
          {/if}
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
