<script lang="ts">
  let {
    text = "",
    bookTitle = "",
    authors = [] as string[],
    note = null as string | null,
  }: {
    text?: string;
    bookTitle?: string;
    authors?: string[];
    note?: string | null;
  } = $props();

  // Strip extra whitespace from multi-line epub selections
  let cleanText = $derived(
    text.split(/\n/).map(line => line.trim()).filter(Boolean).join("")
  );

  let fontSize = $derived(
    cleanText.length < 50 ? 56 : cleanText.length < 100 ? 48 : cleanText.length < 200 ? 42 : cleanText.length < 400 ? 36 : 30,
  );
</script>

<div
  class="share-card"
  style="
    width: 1080px;
    height: 1350px;
    background: #faf7f2;
    padding: 120px 100px 100px;
    box-sizing: border-box;
    position: relative;
    overflow: hidden;
  "
>
  <!-- Corner accents -->
  <div
    style="
      position: absolute;
      top: 48px;
      left: 48px;
      width: 56px;
      height: 56px;
      border-top: 2.5px solid #c4924a;
      border-left: 2.5px solid #c4924a;
      opacity: 0.35;
    "
  ></div>
  <div
    style="
      position: absolute;
      bottom: 48px;
      right: 48px;
      width: 56px;
      height: 56px;
      border-bottom: 2.5px solid #c4924a;
      border-right: 2.5px solid #c4924a;
      opacity: 0.35;
    "
  ></div>

  <!-- Quote mark -->
  <div
    style="
      font-family: 'Playfair Display', Georgia, serif;
      font-size: 120px;
      color: #c4924a;
      line-height: 1;
      text-align: center;
      margin-bottom: 48px;
      opacity: 0.7;
    "
  >
    &ldquo;
  </div>

  <!-- Highlight text -->
  <div
    style="
      font-family: 'Noto Serif TC', 'Playfair Display', Georgia, 'Times New Roman', serif;
      font-size: {fontSize}px;
      font-weight: 400;
      color: #1a1510;
      line-height: 1.85;
      text-align: center;
      letter-spacing: 0.03em;
      word-break: break-word;
      padding: 0 20px;
    "
  >
    {cleanText}
  </div>

  <!-- Note -->
  {#if note}
    <div
      style="
        font-family: 'Inter', 'Noto Serif TC', system-ui, sans-serif;
        font-size: 28px;
        font-style: italic;
        color: #8a7e6d;
        margin-top: 40px;
        text-align: center;
        line-height: 1.6;
        padding: 0 20px;
      "
    >
      {note}
    </div>
  {/if}

  <!-- Bottom section: separator + book info -->
  <div
    style="
      position: absolute;
      bottom: 100px;
      left: 100px;
      right: 100px;
      text-align: center;
    "
  >
    <!-- Gold separator -->
    <div
      style="
        width: 72px;
        height: 2.5px;
        background: #c4924a;
        margin: 0 auto 36px;
        opacity: 0.5;
      "
    ></div>

    <!-- Book title -->
    <div
      style="
        font-family: 'Inter', 'Noto Serif TC', system-ui, sans-serif;
        font-size: 30px;
        font-weight: 600;
        color: #3d3529;
        letter-spacing: 0.01em;
      "
    >
      {bookTitle}
    </div>

    <!-- Authors -->
    {#if authors.length > 0}
      <div
        style="
          font-family: 'Inter', 'Noto Serif TC', system-ui, sans-serif;
          font-size: 26px;
          font-weight: 400;
          color: #8a7e6d;
          margin-top: 10px;
        "
      >
        {authors.join(" / ")}
      </div>
    {/if}
  </div>
</div>
