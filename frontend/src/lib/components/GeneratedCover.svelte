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

  // Insel-Bücherei formula: tone-on-tone patterned binding paper with a
  // cream paste-label. [figure, ground] pairs — the ground is the
  // figure's light mix into cream, low-contrast so the label pops.
  const PAIRS: Array<[string, string]> = [
    ["#8F7420", "#E7DDBE"], // ochre
    ["#7A3229", "#F1E2D6"], // oxblood
    ["#2E5546", "#DCE4DC"], // pine
    ["#33415C", "#DAD8E2"], // indigo
    ["#5A3A55", "#E4DBE2"], // plum
    ["#B4552D", "#F0DFD3"], // persimmon
  ];

  function hash(s: string): number {
    let h = 5381;
    for (let i = 0; i < s.length; i++) h = (h * 33 + s.charCodeAt(i)) >>> 0;
    return h;
  }

  // Independent hash slices so color and pattern don't correlate.
  const h = $derived(hash(title + "\0" + (authors[0] ?? "")));
  const [figure, ground] = $derived(PAIRS[h % PAIRS.length]);
  const pattern = $derived((h >> 4) % 4);
  const author = $derived(authors[0] ?? "");

  // Fixed-px tiles: scale-independent, no moiré at grid size.
  const patternStyle = $derived(
    [
      `background-color:${ground}; background-image:radial-gradient(circle, ${figure} 1.2px, transparent 1.6px); background-size:12px 12px`,
      `background:repeating-linear-gradient(45deg, ${figure} 0 1px, ${ground} 1px 8px)`,
      `background-color:${ground}; background-image:repeating-linear-gradient(0deg, ${figure}40 0 1px, transparent 1px 9px), repeating-linear-gradient(90deg, ${figure}40 0 1px, transparent 1px 9px)`,
      `background-color:${ground}; background-image:radial-gradient(circle, ${figure} 1.1px, transparent 1.5px), radial-gradient(circle, ${figure} 1.1px, transparent 1.5px); background-size:14px 14px; background-position:0 0, 7px 7px`,
    ][pattern],
  );
</script>

<div
  class="relative overflow-hidden rounded-sm book-shadow {className}"
  style="{patternStyle}; container-type:size;"
>
  <div
    class="absolute left-1/2 top-[10%] w-[72%] -translate-x-1/2 bg-[#F7F1E3] px-[5cqw] py-[7cqw] text-center"
    style="border:1px solid {figure}; outline:1px solid {figure}; outline-offset:3px"
  >
    <p
      class="line-clamp-4"
      style="color:#372F24; font-family:var(--font-heading); font-size:{title.length >
      10
        ? 'clamp(10px, 6.5cqw, 17px)'
        : 'clamp(11px, 8.5cqw, 22px)'}; line-height:1.45"
    >
      {title}
    </p>
    <div
      class="mx-auto my-[4cqw] h-1.5 w-1.5 rotate-45"
      style="background:{figure}"
    ></div>
    {#if author}
      <p
        class="truncate"
        style="color:#4A3F2A; font-size:clamp(9px, 4.5cqw, 13px); letter-spacing:0.15em"
      >
        {author}
      </p>
    {/if}
  </div>
</div>
