<script lang="ts">
  let {
    title,
    authors = [],
    class: className = "",
  }: {
    title: string;
    authors?: string[];
    class?: string;
  } = $props();

  // Muted, warm-leaning pairs of [background, ink] that sit well in both
  // themes. The pick is a hash of the title so a book keeps its cover.
  const PALETTE: Array<[string, string]> = [
    ["#77654c", "#f5efe4"], // umber
    ["#6d7b66", "#eff3ea"], // sage
    ["#8a5f52", "#f6ece7"], // clay
    ["#5f7282", "#e9eff4"], // slate
    ["#7d6376", "#f3ecf1"], // mauve
    ["#8f7434", "#f7f1e2"], // ochre
  ];

  function hash(s: string): number {
    let h = 5381;
    for (let i = 0; i < s.length; i++) h = (h * 33 + s.charCodeAt(i)) >>> 0;
    return h;
  }

  const [bg, ink] = $derived(PALETTE[hash(title) % PALETTE.length]);
  // CJK titles set vertically, like a real TW cover; long ones wrap
  // into columns leftward.
  const isCjk = $derived(/[぀-ヿ㐀-䶿一-鿿豈-﫿]/.test(title));
  const author = $derived(authors[0] ?? "");
</script>

<div
  class="relative overflow-hidden rounded-sm book-shadow {className}"
  style="background:{bg}; container-type:size;"
>
  <!-- printed inner frame -->
  <div
    class="pointer-events-none absolute inset-[6%] border"
    style="border-color:{ink}40"
  ></div>

  {#if isCjk}
    <div
      class="absolute inset-[13%] {author
        ? 'bottom-[20%]'
        : ''} flex justify-end overflow-hidden"
    >
      <div
        style="writing-mode:vertical-rl; color:{ink}; font-family:var(--font-heading); font-size:clamp(12px, 11cqw, 30px); letter-spacing:0.18em; line-height:1.9"
      >
        {title}
      </div>
    </div>
  {:else}
    <div
      class="absolute inset-[13%] {author
        ? 'bottom-[24%]'
        : ''} flex items-center justify-center overflow-hidden text-center"
    >
      <span
        class="line-clamp-5"
        style="color:{ink}; font-family:var(--font-heading); font-size:clamp(12px, 10cqw, 26px); line-height:1.35"
      >
        {title}
      </span>
    </div>
  {/if}

  {#if author}
    <span
      class="absolute inset-x-[13%] bottom-[9%] truncate text-center"
      style="color:{ink}b3; font-size:clamp(9px, 6cqw, 15px)"
    >
      {author}
    </span>
  {/if}
</div>
