<script lang="ts">
  import { ArrowLeft } from "@lucide/svelte";

  let {
    href,
    label = "Back",
    onclick,
  }: {
    href: string;
    label?: string;
    onclick?: (e: MouseEvent) => void;
  } = $props();
</script>

<a
  {href}
  class="inline-flex items-center gap-1.5 text-muted-foreground hover:text-foreground transition-colors"
  onclick={onclick
    ? (e) => {
        e.preventDefault();
        onclick(e);
      }
    : undefined}
>
  <ArrowLeft size={18} />
  <span class="text-sm">{label}</span>
</a>
