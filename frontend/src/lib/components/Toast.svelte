<script lang="ts">
  import { fly } from "svelte/transition";
  import { backOut, cubicIn } from "svelte/easing";
  import { toastStore } from "$lib/stores/toast";
  import * as m from "$lib/paraglide/messages.js";
  import { CircleCheck, CircleX, Info, TriangleAlert, X } from "@lucide/svelte";
  import type { ToastType } from "$lib/stores/toast";

  const icons = {
    success: CircleCheck,
    error: CircleX,
    info: Info,
    warning: TriangleAlert,
  } as const;

  // Success is brand-colored (a green card was the only green in the app);
  // the semantic types keep their hue but follow the theme.
  const colors: Record<ToastType, string> = {
    success:
      "bg-[color-mix(in_srgb,var(--primary)_12%,var(--card))] border-primary/40 text-foreground",
    error:
      "bg-red-50 border-red-200 text-red-800 dark:bg-red-950 dark:border-red-900 dark:text-red-200",
    info: "bg-blue-50 border-blue-200 text-blue-800 dark:bg-blue-950 dark:border-blue-900 dark:text-blue-200",
    warning:
      "bg-amber-50 border-amber-200 text-amber-800 dark:bg-amber-950 dark:border-amber-900 dark:text-amber-200",
  };

  // Motion is what catches the eye at the screen's edge; without it a
  // toast appears unnoticed. None for reduced motion.
  const reducedMotion =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // On a phone the column is at the top (the thumb, the tab bar, the
  // reader's bar and the keyboard all live at the bottom): a toast drops
  // in from above the screen's edge and settles with a small overshoot,
  // as a notification banner does, and leaves the way it came. From the
  // `md` breakpoint up it is at the bottom and rises into place. Asked
  // each time a toast comes or goes — the window may have been resized.
  const PHONE = "(max-width: 767px)";
  const onPhone = () => window.matchMedia(PHONE).matches;
  function arrive() {
    if (reducedMotion) return { duration: 0 };
    return onPhone()
      ? { y: -120, duration: 420, easing: backOut }
      : { y: 24, duration: 220 };
  }
  function leave() {
    if (reducedMotion) return { duration: 0 };
    return onPhone()
      ? { y: -96, duration: 200, easing: cubicIn }
      : { y: 8, duration: 160 };
  }

  // A finger pushes a toast back up where it came from. Touch only (a
  // mouse has the close button), and only at the top: it follows the
  // finger upwards, and past a short way — or flicked — it is gone;
  // let go sooner and it settles back. Its clock is already stopped
  // while it is touched (pointerenter / pointerleave below).
  const SWIPE_AWAY_PX = 28;
  const FLICK_PX_PER_MS = 0.4;
  function swipeAway(node: HTMLElement, id: string) {
    let pointer: number | null = null;
    let startY = 0;
    let lastY = 0;
    let lastAt = 0;
    let speed = 0;
    let dragging = false;
    let dragged = false;

    function down(e: PointerEvent) {
      dragged = false;
      if (e.pointerType === "mouse" || !onPhone() || pointer !== null) return;
      pointer = e.pointerId;
      startY = lastY = e.clientY;
      lastAt = e.timeStamp;
      speed = 0;
      dragging = false;
    }
    function move(e: PointerEvent) {
      if (e.pointerId !== pointer) return;
      const dy = e.clientY - startY;
      if (!dragging) {
        if (Math.abs(dy) < 6) return;
        dragging = true;
        // (Captured only once it is a drag: a tap on Retry or on the
        // close button stays a click on that button.)
        node.setPointerCapture(e.pointerId);
        node.style.transition = "none";
      }
      const dt = e.timeStamp - lastAt;
      if (dt > 0) speed = (e.clientY - lastY) / dt;
      lastY = e.clientY;
      lastAt = e.timeStamp;
      // Up freely; down only a little, against resistance.
      node.style.transform = `translateY(${dy < 0 ? dy : dy * 0.15}px)`;
    }
    function up(e: PointerEvent) {
      if (e.pointerId !== pointer) return;
      pointer = null;
      if (!dragging) return;
      dragging = false;
      dragged = true;
      const dy = e.clientY - startY;
      if (
        e.type === "pointerup" &&
        (dy < -SWIPE_AWAY_PX || (dy < 0 && speed < -FLICK_PX_PER_MS))
      ) {
        // (It leaves from where the finger left it: the out transition
        // carries on from the transform it finds.)
        toastStore.remove(id);
        return;
      }
      node.style.transition = reducedMotion ? "" : "transform 180ms ease-out";
      node.style.transform = "";
    }
    // A drag that ended on a button is not a press of it.
    function click(e: MouseEvent) {
      if (!dragged) return;
      dragged = false;
      e.preventDefault();
      e.stopPropagation();
    }
    node.addEventListener("pointerdown", down);
    node.addEventListener("pointermove", move);
    node.addEventListener("pointerup", up);
    node.addEventListener("pointercancel", up);
    node.addEventListener("click", click, true);
    return {
      destroy() {
        node.removeEventListener("pointerdown", down);
        node.removeEventListener("pointermove", move);
        node.removeEventListener("pointerup", up);
        node.removeEventListener("pointercancel", up);
        node.removeEventListener("click", click, true);
      },
    };
  }

  // A message that comes again while its toast is showing (the same
  // failure, once more) is felt: a small shake — a dip in opacity for
  // reduced motion.
  function nudge(node: HTMLElement, repeats: number) {
    let felt = repeats;
    return {
      update(now: number) {
        if (now === felt) return;
        felt = now;
        const reduced = window.matchMedia(
          "(prefers-reduced-motion: reduce)",
        ).matches;
        node.animate(
          reduced
            ? [{ opacity: 1 }, { opacity: 0.5 }, { opacity: 1 }]
            : [0, -5, 5, -3, 3, 0].map((x) => ({
                transform: `translateX(${x}px)`,
              })),
          { duration: reduced ? 400 : 320, easing: "ease-out" },
        );
      },
    };
  }

  const iconColors: Record<ToastType, string> = {
    success: "text-primary",
    error: "",
    info: "",
    warning: "",
  };
</script>

<!-- Above everything that can be open when a toast is raised — sheets,
     sidebars and dialogs (z-50), the reader's viewers (z-60/70), the
     book page's work picker (z-100) — and under the launch splash
     (z-200). On a phone the newest is nearest the top edge
     (`flex-col-reverse`): it comes in where the eye already is and
     moves the older one down, as banners do. -->
<div
  class="fixed left-1/2 -translate-x-1/2 z-[150] flex flex-col-reverse md:flex-col items-center gap-2 max-w-sm w-full pointer-events-none px-4 toast-position"
  data-testid="toasts"
>
  {#each $toastStore as toast (toast.id)}
    {@const IconComponent = icons[toast.type]}
    <div
      class="toast flex items-start gap-3 px-4 py-3 rounded-2xl border shadow-lg pointer-events-auto w-full {colors[
        toast.type
      ]}"
      role="status"
      data-testid={toast.testId}
      data-repeats={toast.repeats ?? 0}
      use:nudge={toast.repeats ?? 0}
      use:swipeAway={toast.id}
      in:fly={arrive()}
      out:fly={leave()}
      onpointerenter={() => toastStore.pause(toast.id)}
      onpointerleave={() => toastStore.resume(toast.id)}
    >
      <IconComponent
        size={18}
        class="flex-shrink-0 mt-0.5 {iconColors[toast.type]}"
      />
      <!-- (A new node each time it is said again: read again.) -->
      {#key toast.repeats}
        <span class="text-sm flex-1 min-w-0 break-words">{toast.message}</span>
      {/key}
      {#if toast.action}
        <button
          class="flex-shrink-0 text-sm font-semibold underline underline-offset-2 hover:opacity-80"
          onclick={() => {
            toast.action?.onclick();
            toastStore.remove(toast.id);
          }}
        >
          {toast.action.label}
        </button>
      {/if}
      <button
        aria-label={m.common_close()}
        class="flex-shrink-0 opacity-70 hover:opacity-100"
        onclick={() => toastStore.remove(toast.id)}
      >
        <X size={16} />
      </button>
    </div>
  {/each}
</div>

<style>
  /* Phone: at the top, under the status bar (the notch, in the app). */
  .toast-position {
    top: calc(env(safe-area-inset-top, 0px) + 0.5rem);
  }

  /* A finger on a toast moves the toast, not the page under it. */
  .toast {
    touch-action: none;
  }

  /* From `md` up: at the bottom, above the safe area.
     --transfer-offset: the transfer panel's height while it shows. */
  @media (min-width: 768px) {
    .toast-position {
      top: auto;
      bottom: calc(
        1rem + env(safe-area-inset-bottom, 0px) + var(--transfer-offset, 0px)
      );
    }
    .toast {
      touch-action: auto;
    }
  }
</style>
