<script lang="ts">
  import SparkMD5 from "spark-md5";
  import { toastStore } from "$lib/stores/toast";
  import { confirmDialog } from "$lib/stores/confirm";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import * as Dialog from "$lib/components/ui/dialog";
  import { Loader2 } from "@lucide/svelte";
  import * as m from "$lib/paraglide/messages.js";
  import {
    KosyncError,
    registerAccount,
    verifyAuth,
    type KosyncCredentials,
  } from "$lib/kosync/client";
  import type { KosyncAccount } from "$lib/services/kosyncAccount";

  let { open = $bindable(false) }: { open?: boolean } = $props();

  let account = $state<KosyncAccount | null>(null);
  let loaded = $state(false);
  let formUrl = $state("https://sync.koreader.rocks");
  let formUsername = $state("");
  let formPassword = $state("");
  let formError = $state("");
  let busy = $state<"login" | "register" | null>(null);

  $effect(() => {
    if (!open) return;
    formError = "";
    void (async () => {
      const { getKosyncAccount } = await import("$lib/services/kosyncAccount");
      account = await getKosyncAccount();
      loaded = true;
    })();
  });

  function hostOf(url: string): string {
    try {
      return new URL(url).host;
    } catch {
      return url;
    }
  }

  function errorMessage(err: unknown): string {
    if (err instanceof KosyncError) {
      switch (err.kind) {
        case "auth":
          return m.kosync_error_auth();
        case "network":
          return m.kosync_error_network();
        case "conflict":
          return m.kosync_error_username_taken();
        default:
          // Server-provided messages are user-meaningful here — BeePub's own
          // /users/create 403 explains that sync uses the BeePub account.
          return err.serverMessage ?? m.kosync_error_server();
      }
    }
    return (err as Error).message;
  }

  async function attempt(
    kind: "login" | "register",
    creds: KosyncCredentials,
  ): Promise<void> {
    if (kind === "register") await registerAccount(creds);
    await verifyAuth(creds);
  }

  async function submit(kind: "login" | "register") {
    formError = "";
    const url = formUrl.trim();
    let parsed: URL;
    try {
      parsed = new URL(url);
    } catch {
      formError = m.kosync_url_invalid();
      return;
    }
    if (parsed.protocol !== "https:") {
      formError = m.kosync_url_invalid();
      return;
    }
    const username = formUsername.trim();
    if (!username || !formPassword) return;
    busy = kind;
    try {
      let creds: KosyncCredentials = {
        serverUrl: url.replace(/\/+$/, ""),
        username,
        // The kosync convention: md5(password) is the credential on the
        // wire, for registration too — the plaintext never leaves this form.
        userkey: SparkMD5.hash(formPassword),
      };
      try {
        await attempt(kind, creds);
      } catch (err) {
        // A bare origin often means a BeePub server whose kosync lives at
        // /kosync (same footgun as OPDS at /opds) — probe it once. Auth and
        // conflict answers are real kosync responses, so don't second-guess
        // those; when the probe fails too, its error is the meaningful one
        // (e.g. BeePub's "use your BeePub credentials" refusal).
        const pathless = parsed.pathname === "/" || parsed.pathname === "";
        const probeable =
          err instanceof KosyncError &&
          (err.kind === "http" || err.kind === "parse");
        if (!pathless || !probeable) throw err;
        creds = { ...creds, serverUrl: `${parsed.origin}/kosync` };
        await attempt(kind, creds);
        formUrl = creds.serverUrl;
      }
      const { setKosyncAccount } = await import("$lib/services/kosyncAccount");
      account = await setKosyncAccount(creds);
      formPassword = "";
      toastStore.success(
        kind === "register"
          ? m.kosync_register_success()
          : m.kosync_login_success(),
      );
    } catch (err) {
      formError = errorMessage(err);
    } finally {
      busy = null;
    }
  }

  async function setAutoSync(on: boolean) {
    if (!account || account.autoSync === on) return;
    const { setKosyncAutoSync } = await import("$lib/services/kosyncAccount");
    account = await setKosyncAutoSync(on);
  }

  async function handleLogout() {
    const current = account;
    if (!current) return;
    if (
      !(await confirmDialog({
        title: m.kosync_logout_confirm({ host: hostOf(current.serverUrl) }),
        destructive: true,
      }))
    )
      return;
    const { clearKosyncAccount } = await import("$lib/services/kosyncAccount");
    await clearKosyncAccount();
    account = null;
    toastStore.success(m.kosync_logged_out());
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="sm:max-w-md bg-popover">
    <Dialog.Header>
      <Dialog.Title>{m.kosync_title()}</Dialog.Title>
      <Dialog.Description>{m.kosync_dialog_desc()}</Dialog.Description>
    </Dialog.Header>
    {#if !loaded}
      <div class="py-8"></div>
    {:else if account}
      <p class="text-sm text-foreground">
        {m.kosync_connected_as({
          username: account.username,
          host: hostOf(account.serverUrl),
        })}
      </p>
      <div class="flex items-center justify-between">
        <Label>{m.kosync_auto_sync()}</Label>
        <div class="flex gap-1">
          <Button
            size="sm"
            class="rounded-xl"
            variant={account.autoSync ? "default" : "outline"}
            onclick={() => setAutoSync(true)}
          >
            {m.kosync_auto_on()}
          </Button>
          <Button
            size="sm"
            class="rounded-xl"
            variant={account.autoSync ? "outline" : "default"}
            onclick={() => setAutoSync(false)}
          >
            {m.kosync_auto_off()}
          </Button>
        </div>
      </div>
      <p class="text-xs text-muted-foreground">
        {account.autoSync ? m.kosync_auto_on_hint() : m.kosync_auto_off_hint()}
      </p>
      <Dialog.Footer>
        <Button
          variant="outline"
          class="rounded-xl"
          onclick={() => (open = false)}>{m.common_close()}</Button
        >
        <Button variant="destructive" class="rounded-xl" onclick={handleLogout}>
          {m.kosync_logout()}
        </Button>
      </Dialog.Footer>
    {:else}
      <form
        onsubmit={(e) => {
          e.preventDefault();
          submit("login");
        }}
        class="space-y-4"
      >
        <div class="space-y-1.5">
          <Label for="kosync-url">{m.kosync_server_label()}</Label>
          <Input
            id="kosync-url"
            bind:value={formUrl}
            placeholder={m.kosync_server_placeholder()}
            autocapitalize="none"
            autocomplete="url"
            autocorrect="off"
            spellcheck={false}
            inputmode="url"
            required
          />
        </div>
        <div class="space-y-1.5">
          <Label for="kosync-username">{m.kosync_username_label()}</Label>
          <Input
            id="kosync-username"
            bind:value={formUsername}
            autocapitalize="none"
            autocomplete="off"
            autocorrect="off"
            spellcheck={false}
            required
          />
        </div>
        <div class="space-y-1.5">
          <Label for="kosync-password">{m.kosync_password_label()}</Label>
          <Input
            id="kosync-password"
            type="password"
            bind:value={formPassword}
            autocomplete="off"
            required
          />
        </div>
        {#if formError}
          <p class="text-sm text-red-600">{formError}</p>
        {/if}
        <Dialog.Footer>
          <Button
            type="button"
            variant="outline"
            class="rounded-xl"
            disabled={busy !== null || !formUsername.trim() || !formPassword}
            onclick={() => submit("register")}
          >
            {#if busy === "register"}
              <Loader2 class="animate-spin" size={16} />
            {/if}
            {m.kosync_register()}
          </Button>
          <Button type="submit" disabled={busy !== null} class="rounded-xl">
            {#if busy === "login"}
              <Loader2 class="animate-spin" size={16} />
            {/if}
            {m.kosync_login()}
          </Button>
        </Dialog.Footer>
      </form>
    {/if}
  </Dialog.Content>
</Dialog.Root>
