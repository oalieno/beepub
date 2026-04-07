<script lang="ts">
  import Modal from "$lib/components/Modal.svelte";
  import * as m from "$lib/paraglide/messages.js";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import * as Select from "$lib/components/ui/select";

  const ISSUE_OPTIONS = $derived([
    { value: "corrupt_file", label: m.report_corrupt_file() },
    { value: "wrong_metadata", label: m.report_wrong_metadata() },
    { value: "cant_open", label: m.report_cant_open() },
    { value: "other", label: m.report_other() },
  ]);

  let {
    bookId,
    open = $bindable(false),
    onreported,
  }: {
    bookId: string;
    open: boolean;
    onreported: () => void;
  } = $props();

  let reportForm = $state({ issue_type: "", description: "" });
  let submitting = $state(false);

  async function handleSubmit() {
    if (!reportForm.issue_type) return;
    submitting = true;
    try {
      await booksApi.reportIssue(bookId, {
        issue_type: reportForm.issue_type,
        description: reportForm.description || undefined,
      });
      open = false;
      reportForm = { issue_type: "", description: "" };
      onreported();
      toastStore.success(m.report_submitted());
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      submitting = false;
    }
  }
</script>

<Modal title={m.report_title()} {open} onclose={() => (open = false)}>
  <div class="space-y-4">
    <div class="space-y-1">
      <p class="text-sm text-muted-foreground">{m.report_issue_type()}</p>
      <Select.Root
        type="single"
        value={reportForm.issue_type || undefined}
        onValueChange={(v) => (reportForm.issue_type = v)}
      >
        <Select.Trigger>
          {#if reportForm.issue_type}
            {ISSUE_OPTIONS.find((o) => o.value === reportForm.issue_type)
              ?.label}
          {:else}
            {m.report_select_placeholder()}
          {/if}
        </Select.Trigger>
        <Select.Content>
          {#each ISSUE_OPTIONS as opt}
            <Select.Item value={opt.value}>{opt.label}</Select.Item>
          {/each}
        </Select.Content>
      </Select.Root>
    </div>
    <div class="space-y-1">
      <label class="block text-sm text-muted-foreground" for="report-desc"
        >{m.report_description_optional()}</label
      >
      <textarea
        id="report-desc"
        bind:value={reportForm.description}
        rows={4}
        maxlength={2000}
        class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 resize-none text-sm"
        placeholder={m.report_describe_placeholder()}
      ></textarea>
    </div>
    <div class="flex justify-end gap-2 pt-2">
      <button
        class="px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
        onclick={() => (open = false)}>{m.common_cancel()}</button
      >
      <button
        class="px-5 py-2.5 text-sm bg-primary hover:bg-primary/90 text-primary-foreground font-semibold rounded-xl disabled:opacity-50"
        onclick={handleSubmit}
        disabled={submitting || !reportForm.issue_type}
      >
        {submitting ? m.report_submitting() : m.report_submit()}
      </button>
    </div>
  </div>
</Modal>
