<script lang="ts">
  import { X } from "@lucide/svelte";

  let {
    src,
    darkMode = false,
    onclose,
  }: {
    src: string;
    darkMode?: boolean;
    onclose?: () => void;
  } = $props();

  let scale = $state(1);
  let translateX = $state(0);
  let translateY = $state(0);

  // Pan state
  let isPanning = $state(false);
  let panStartX = 0;
  let panStartY = 0;
  let panStartTranslateX = 0;
  let panStartTranslateY = 0;

  // Pinch state
  let initialPinchDistance = 0;
  let initialPinchScale = 1;

  // Double-tap state
  let lastTapTime = 0;

  const MIN_SCALE = 1;
  const MAX_SCALE = 5;

  function resetTransform() {
    scale = 1;
    translateX = 0;
    translateY = 0;
  }

  function clampScale(s: number): number {
    return Math.min(MAX_SCALE, Math.max(MIN_SCALE, s));
  }

  function handleWheel(e: WheelEvent) {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    const newScale = clampScale(scale * delta);
    if (newScale === MIN_SCALE) {
      resetTransform();
    } else {
      scale = newScale;
    }
  }

  function getTouchDistance(t1: Touch, t2: Touch): number {
    const dx = t1.clientX - t2.clientX;
    const dy = t1.clientY - t2.clientY;
    return Math.sqrt(dx * dx + dy * dy);
  }

  function handleTouchStart(e: TouchEvent) {
    if (e.touches.length === 2) {
      // Pinch start
      isPanning = false;
      initialPinchDistance = getTouchDistance(e.touches[0], e.touches[1]);
      initialPinchScale = scale;
    } else if (e.touches.length === 1) {
      // Double-tap detection
      const now = Date.now();
      if (now - lastTapTime < 300) {
        e.preventDefault();
        if (scale > 1) {
          resetTransform();
        } else {
          scale = 2.5;
        }
        lastTapTime = 0;
        return;
      }
      lastTapTime = now;

      // Pan start (only when zoomed)
      if (scale > 1) {
        isPanning = true;
        panStartX = e.touches[0].clientX;
        panStartY = e.touches[0].clientY;
        panStartTranslateX = translateX;
        panStartTranslateY = translateY;
      }
    }
  }

  function handleTouchMove(e: TouchEvent) {
    if (e.touches.length === 2) {
      // Pinch zoom
      e.preventDefault();
      const dist = getTouchDistance(e.touches[0], e.touches[1]);
      const newScale = clampScale(
        initialPinchScale * (dist / initialPinchDistance),
      );
      if (newScale === MIN_SCALE) {
        resetTransform();
      } else {
        scale = newScale;
      }
    } else if (e.touches.length === 1 && isPanning && scale > 1) {
      // Pan
      e.preventDefault();
      translateX =
        panStartTranslateX + (e.touches[0].clientX - panStartX) / scale;
      translateY =
        panStartTranslateY + (e.touches[0].clientY - panStartY) / scale;
    }
  }

  function handleTouchEnd(e: TouchEvent) {
    if (e.touches.length < 2) {
      initialPinchDistance = 0;
    }
    if (e.touches.length === 0) {
      isPanning = false;
    }
  }

  // Mouse pan (desktop)
  function handleMouseDown(e: MouseEvent) {
    if (scale > 1) {
      isPanning = true;
      panStartX = e.clientX;
      panStartY = e.clientY;
      panStartTranslateX = translateX;
      panStartTranslateY = translateY;
      e.preventDefault();
    }
  }

  function handleMouseMove(e: MouseEvent) {
    if (isPanning && scale > 1) {
      translateX = panStartTranslateX + (e.clientX - panStartX) / scale;
      translateY = panStartTranslateY + (e.clientY - panStartY) / scale;
    }
  }

  function handleMouseUp() {
    isPanning = false;
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Escape") onclose?.();
  }

  function handleBackdropClick(e: MouseEvent) {
    // Close only if clicking the backdrop (not the image)
    if (e.target === e.currentTarget) {
      onclose?.();
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="fixed inset-0 z-[70] flex items-center justify-center"
  onclick={handleBackdropClick}
>
  <div class="absolute inset-0 bg-black/85"></div>

  <!-- Close button -->
  <button
    class="absolute top-4 right-4 z-10 p-2 rounded-full bg-black/50 text-white/80 hover:text-white transition-colors"
    onclick={() => onclose?.()}
  >
    <X size={22} />
  </button>

  <!-- Image container -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="relative w-full h-full flex items-center justify-center overflow-hidden"
    style="cursor: {scale > 1 ? (isPanning ? 'grabbing' : 'grab') : 'zoom-in'}; touch-action: none;"
    onwheel={handleWheel}
    ontouchstart={handleTouchStart}
    ontouchmove={handleTouchMove}
    ontouchend={handleTouchEnd}
    onmousedown={handleMouseDown}
    onmousemove={handleMouseMove}
    onmouseup={handleMouseUp}
    onmouseleave={handleMouseUp}
  >
    <img
      {src}
      alt=""
      class="max-w-full max-h-full object-contain select-none pointer-events-none"
      style="transform: scale({scale}) translate({translateX}px, {translateY}px); transition: {isPanning ? 'none' : 'transform 0.2s ease'};"
      draggable="false"
    />
  </div>
</div>
