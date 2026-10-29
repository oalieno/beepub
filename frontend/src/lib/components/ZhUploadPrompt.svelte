<script lang="ts">
  /**
   * After an upload that brought Simplified Chinese books: ask once for
   * the batch whether to convert them (zhConvert). Mounted app-wide, since
   * uploads finish in the background, wherever the reader has gone.
   */
  import ZhConvertDialog from "$lib/components/ZhConvertDialog.svelte";
  import { simplifiedUploads } from "$lib/services/zhConvert";

  let open = $derived($simplifiedUploads.length > 0);
</script>

<ZhConvertDialog
  {open}
  upload
  books={$simplifiedUploads}
  onclose={() => simplifiedUploads.set([])}
/>
