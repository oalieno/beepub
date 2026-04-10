<script lang="ts">
  import { sanitizeHtml } from "$lib/sanitize";

  let {
    content,
    darkMode = false,
    fontSize = 16,
    isRtl = false,
    sourcePath = "",
    onclose,
    onnavigate,
  }: {
    content: string;
    darkMode?: boolean;
    fontSize?: number;
    isRtl?: boolean;
    sourcePath?: string;
    onclose: () => void;
    onnavigate?: (href: string) => void;
  } = $props();

  function normalizeHref(rawHref: string): string | null {
    const href = (rawHref ?? "").trim();
    if (!href || href.startsWith("javascript:")) return null;

    const basePath = sourcePath || "";
    const baseUrl = `https://epub.local/${basePath}`;
    const resolved = new URL(href, baseUrl);

    if (resolved.origin !== "https://epub.local") return null;

    const path = resolved.pathname.replace(/^\/+/, "");
    const hash = resolved.hash || "";
    return path || hash ? `${path}${hash}` : null;
  }

  async function handleContentClick(e: MouseEvent) {
    const target = e.target as HTMLElement | null;
    const anchor = target?.closest?.("a") as HTMLAnchorElement | null;
    if (!anchor) return;

    const hrefAttr = anchor.getAttribute("href") ?? "";
    const normalized = normalizeHref(hrefAttr);
    if (!normalized) return;

    e.preventDefault();
    onclose();
    onnavigate?.(normalized);
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="absolute inset-0 z-50 flex items-center justify-center"
  onclick={onclose}
  onkeydown={(e) => {
    if (e.key === "Escape") onclose();
  }}
>
  <div
    class="footnote-content rounded-lg shadow-2xl p-8 leading-relaxed {darkMode
      ? 'bg-gray-800 text-gray-200 border-2 border-gray-500'
      : 'bg-white text-gray-900 border-2 border-black'}"
    style="width: 50%; height: 50%; overflow-y: auto; font-size: {fontSize}px;{isRtl
      ? ' writing-mode: vertical-rl; max-height: none; overflow-x: auto; overflow-y: hidden;'
      : ''}"
    onclick={async (e: MouseEvent) => {
      e.stopPropagation();
      await handleContentClick(e);
    }}
    onkeydown={(e) => e.stopPropagation()}
  >
    {@html sanitizeHtml(content)}
  </div>
</div>

<style>
  :global(.footnote-content a),
  :global(.footnote-content sup) {
    text-orientation: upright;
    text-combine-upright: all;
  }
</style>
