<script lang="ts">
  import type { Snippet } from "svelte";
  import OpenedFilesDialog from "$lib/components/OpenedFilesDialog.svelte";

  let { children }: { children: Snippet } = $props();
</script>

{@render children()}

<!-- A book opened from Files mid-read asks right away; the transfer
     panel isn't here, so its progress shows once the reader is left. -->
<OpenedFilesDialog />
