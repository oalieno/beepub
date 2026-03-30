<script lang="ts">
  import Modal from "$lib/components/Modal.svelte";
  import { booksApi } from "$lib/api/books";
  import { toastStore } from "$lib/stores/toast";
  import * as Select from "$lib/components/ui/select";

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
      toastStore.success("Report submitted");
    } catch (e) {
      toastStore.error((e as Error).message);
    } finally {
      submitting = false;
    }
  }
</script>

<Modal title="Report Issue" {open} onclose={() => (open = false)}>
  <div class="space-y-4">
    <div class="space-y-1">
      <p class="text-sm text-muted-foreground">Issue type</p>
      <Select.Root
        type="single"
        value={reportForm.issue_type || undefined}
        onValueChange={(v) => (reportForm.issue_type = v)}
      >
        <Select.Trigger>
          {#if reportForm.issue_type}
            {{
              corrupt_file: "Corrupt file",
              wrong_metadata: "Wrong metadata",
              cant_open: "Can't open",
              other: "Other",
            }[reportForm.issue_type]}
          {:else}
            Select an issue...
          {/if}
        </Select.Trigger>
        <Select.Content>
          <Select.Item value="corrupt_file">Corrupt file</Select.Item>
          <Select.Item value="wrong_metadata">Wrong metadata</Select.Item>
          <Select.Item value="cant_open">Can't open</Select.Item>
          <Select.Item value="other">Other</Select.Item>
        </Select.Content>
      </Select.Root>
    </div>
    <div class="space-y-1">
      <label class="block text-sm text-muted-foreground" for="report-desc"
        >Description (optional)</label
      >
      <textarea
        id="report-desc"
        bind:value={reportForm.description}
        rows={4}
        maxlength={2000}
        class="w-full border border-input bg-background rounded-xl px-3 py-2.5 text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 resize-none text-sm"
        placeholder="Describe the issue..."
      ></textarea>
    </div>
    <div class="flex justify-end gap-2 pt-2">
      <button
        class="px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
        onclick={() => (open = false)}>Cancel</button
      >
      <button
        class="px-5 py-2.5 text-sm bg-primary hover:bg-primary/90 text-primary-foreground font-semibold rounded-xl disabled:opacity-50"
        onclick={handleSubmit}
        disabled={submitting || !reportForm.issue_type}
      >
        {submitting ? "Submitting..." : "Submit Report"}
      </button>
    </div>
  </div>
</Modal>
