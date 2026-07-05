<script lang="ts">
  import * as Dialog from "$lib/components/ui/dialog";
  import { Button } from "$lib/components/ui/button";
  import { confirmRequest } from "$lib/stores/confirm";
  import * as m from "$lib/paraglide/messages.js";

  let request = $derived($confirmRequest);
</script>

{#if request}
  <Dialog.Root
    open={true}
    onOpenChange={(open) => {
      if (!open) request?.resolve(false);
    }}
  >
    <Dialog.Content class="sm:max-w-sm bg-popover" showCloseButton={false}>
      <Dialog.Header>
        <Dialog.Title>{request.title}</Dialog.Title>
        {#if request.description}
          <Dialog.Description>{request.description}</Dialog.Description>
        {/if}
      </Dialog.Header>
      <Dialog.Footer class="gap-2">
        <Button
          variant="outline"
          class="rounded-xl"
          onclick={() => request?.resolve(false)}
        >
          {request.cancelLabel ?? m.common_cancel()}
        </Button>
        <Button
          variant={request.destructive ? "destructive" : "default"}
          class="rounded-xl"
          onclick={() => request?.resolve(true)}
        >
          {request.confirmLabel ??
            (request.destructive ? m.common_delete() : m.common_confirm())}
        </Button>
      </Dialog.Footer>
    </Dialog.Content>
  </Dialog.Root>
{/if}
