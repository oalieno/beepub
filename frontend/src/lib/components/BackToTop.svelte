<script lang="ts">
  import { onMount } from "svelte";
  import { ArrowUp } from "@lucide/svelte";

  let { threshold = 400, bottomOffset = "5.5rem" } = $props<{
    threshold?: number;
    bottomOffset?: string;
  }>();

  let visible = $state(false);

  function onScroll() {
    visible = window.scrollY > threshold;
  }

  onMount(() => {
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  });

  function scrollToTop() {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
</script>

{#if visible}
  <button
    onclick={scrollToTop}
    class="fixed right-4 z-30 md:hidden h-11 w-11 flex items-center justify-center bg-card card-soft rounded-full text-foreground shadow-lg active:scale-95 transition-transform"
    style="bottom: calc({bottomOffset} + env(safe-area-inset-bottom));"
    aria-label="Back to top"
  >
    <ArrowUp size={20} />
  </button>
{/if}
