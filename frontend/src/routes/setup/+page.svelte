<script lang="ts">
  import { goto } from "$app/navigation";
  import { setServerUrl } from "$lib/api/client";
  import { toastStore } from "$lib/stores/toast";
  import { BookOpen, Server, LoaderCircle } from "@lucide/svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";

  let serverUrl = $state("");
  let loading = $state(false);
  let error = $state("");

  async function handleConnect() {
    error = "";
    let url = serverUrl.trim().replace(/\/+$/, "");
    if (!url) {
      error = "Please enter your server URL";
      return;
    }

    // Add https:// if no protocol specified
    if (!url.startsWith("http://") && !url.startsWith("https://")) {
      url = "https://" + url;
    }

    loading = true;
    try {
      const res = await fetch(`${url}/api/auth/me`, {
        method: "GET",
        signal: AbortSignal.timeout(10000),
      });
      // 401 is fine — means the server is reachable and responding
      if (res.ok || res.status === 401) {
        setServerUrl(url);
        toastStore.success("Connected to server!");
        goto("/login");
        return;
      }
      error = `Server responded with HTTP ${res.status}`;
    } catch (e) {
      const msg = (e as Error).message || "";
      if (msg.includes("timeout") || msg.includes("TimeoutError")) {
        error = "Connection timed out. Check the URL and try again.";
      } else {
        error =
          "Cannot reach server. Check the URL and make sure the server is running.";
      }
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head>
  <title>BeePub - Server Setup</title>
</svelte:head>

<div class="min-h-screen flex items-center justify-center px-4">
  <div class="w-full max-w-sm">
    <!-- Logo -->
    <div class="text-center mb-8">
      <div
        class="w-16 h-16 rounded-2xl bg-primary/10 flex items-center justify-center mx-auto mb-4"
      >
        <BookOpen size={28} class="text-primary" />
      </div>
      <h1 class="text-3xl font-bold" style="font-family: var(--font-heading)">
        BeePub
      </h1>
      <p class="text-muted-foreground mt-1">Connect to your server</p>
    </div>

    <!-- Card -->
    <div class="bg-card card-soft rounded-2xl p-6">
      <div class="flex items-center gap-2 mb-4 text-muted-foreground">
        <Server size={18} />
        <span class="text-sm">Enter your BeePub server address</span>
      </div>

      <form
        onsubmit={(e) => {
          e.preventDefault();
          handleConnect();
        }}
        class="space-y-4"
      >
        <div class="space-y-1.5">
          <Label for="server-url" class="text-sm font-medium">Server URL</Label>
          <Input
            id="server-url"
            type="url"
            bind:value={serverUrl}
            placeholder="https://beepub.example.com"
            required
            class="rounded-xl h-11"
          />
        </div>

        {#if error}
          <p class="text-sm text-destructive">{error}</p>
        {/if}

        <Button
          type="submit"
          disabled={loading}
          class="w-full rounded-xl h-11 text-sm font-semibold"
        >
          {#if loading}
            <LoaderCircle size={16} class="animate-spin mr-2" />
            Connecting...
          {:else}
            Connect
          {/if}
        </Button>
      </form>
    </div>
  </div>
</div>
