/**
 * The app's navigation, defined once. The mode only decides which entries
 * exist (an allowlist): local mode is the server nav minus what needs a
 * server, plus its own settings page. The tab bar, the phone top bar's
 * titles and the desktop sidebar all read from here.
 */
import type { Component } from "svelte";
import {
  ArrowLeftRight,
  BookCopy,
  Compass,
  Highlighter,
  Home,
  Library,
  Rss,
  Settings,
  ShelvingUnit,
  User,
} from "@lucide/svelte";
import * as m from "$lib/paraglide/messages.js";

export type NavMode = "server" | "local";

export interface NavItem {
  href: string;
  label: string;
  icon: Component;
  match: (path: string) => boolean;
}

interface NavContext {
  mode: NavMode;
  /** Where the libraries entry jumps (the active library). */
  libraryHref: string;
  native: boolean;
  admin: boolean;
}

const home = (): NavItem => ({
  href: "/",
  label: m.nav_home(),
  icon: Home,
  match: (p) => p === "/",
});

/** The phone tab bar. */
export function navTabs(ctx: NavContext): NavItem[] {
  if (ctx.mode === "local") {
    return [
      home(),
      {
        href: "/local",
        label: m.local_nav_books(),
        icon: BookCopy,
        match: isLocalShelfPath,
      },
      {
        href: "/local/highlights",
        label: m.nav_highlights(),
        icon: Highlighter,
        match: (p) => p.startsWith("/local/highlights"),
      },
      {
        href: "/local/settings",
        label: m.local_nav_settings(),
        icon: Settings,
        match: (p) => p.startsWith("/local/settings"),
      },
    ];
  }
  return [
    home(),
    shelves(),
    libraries(ctx, BookCopy),
    {
      href: "/discover",
      label: m.nav_discover(),
      icon: Compass,
      match: (p) => p.startsWith("/discover"),
    },
    {
      href: "/profile",
      label: m.nav_profile(),
      icon: User,
      match: (p) => p.startsWith("/profile"),
    },
  ];
}

/** The desktop (and iPad) sidebar's main links. */
export function navLinks(ctx: NavContext): NavItem[] {
  // Catalogs import into the device, so they belong to the local library.
  const catalogs: NavItem[] =
    ctx.native && ctx.mode === "local"
      ? [
          {
            href: "/catalogs",
            label: m.nav_catalogs(),
            icon: Rss,
            match: (p) => p.startsWith("/catalogs"),
          },
        ]
      : [];
  const catalogsAndMode: NavItem[] = ctx.native
    ? [
        ...catalogs,
        {
          href: "/mode",
          // Named by where it goes: the two sides are places, not modes.
          label:
            ctx.mode === "local"
              ? m.mode_switch_to_server()
              : m.mode_switch_to_local(),
          icon: ArrowLeftRight,
          match: (p) => p === "/mode",
        },
      ]
    : [];
  if (ctx.mode === "local") {
    const [homeTab, books, highlights, settings] = navTabs(ctx);
    return [homeTab, books, highlights, ...catalogsAndMode, settings];
  }
  return [
    home(),
    shelves(),
    libraries(ctx, Library),
    {
      href: "/highlights",
      label: m.nav_highlights(),
      icon: Highlighter,
      match: (p) => p.startsWith("/highlights"),
    },
    {
      href: "/discover",
      label: m.nav_discover(),
      icon: Compass,
      match: (p) => p.startsWith("/discover"),
    },
    ...catalogsAndMode,
    // Instance-level administration, not a personal setting — it lives in
    // the global nav rather than behind the profile page.
    ...(ctx.admin
      ? [
          {
            href: "/admin",
            label: m.nav_admin(),
            icon: Settings,
            match: (p: string) => p.startsWith("/admin"),
          },
        ]
      : []),
  ];
}

/** The phone top bar's title for a path. Deeper prefixes first. */
export function navTitle(mode: NavMode, path: string): string {
  const titles: [string, string][] =
    mode === "local"
      ? [
          ["/local/highlights", m.nav_highlights()],
          ["/local/settings", m.local_nav_settings()],
          ["/local", m.local_nav_books()],
          ["/catalogs", m.nav_catalogs()],
        ]
      : [
          ["/my-books", m.nav_shelves()],
          ["/libraries", m.nav_libraries()],
          ["/bookshelves", m.nav_shelves()],
          ["/highlights", m.nav_highlights()],
          ["/discover", m.nav_discover()],
          ["/gacha", m.nav_gacha()],
          ["/admin", m.nav_admin()],
          ["/profile", m.nav_profile()],
        ];
  if (path === "/") return m.nav_home();
  for (const [prefix, title] of titles) {
    if (path.startsWith(prefix)) return title;
  }
  return "BeePub";
}

function shelves(): NavItem {
  return {
    href: "/bookshelves",
    label: m.nav_shelves(),
    icon: ShelvingUnit,
    // /my-books is the system-shelf detail route — keep the entry lit there.
    match: (p) => p.startsWith("/bookshelves") || p.startsWith("/my-books"),
  };
}

function libraries(ctx: NavContext, icon: Component): NavItem {
  return {
    // Calibre-style: jump straight into the active library; the cards
    // page one level up (via its back button) is the switcher.
    href: ctx.libraryHref,
    label: m.nav_libraries(),
    icon,
    match: (p) => p.startsWith("/libraries"),
  };
}

/** The device shelf, its book pages, and the catalogs it imports from. */
function isLocalShelfPath(p: string): boolean {
  return (
    p === "/local" ||
    p.startsWith("/catalogs") ||
    (/^\/local\/[^/]+$/.test(p) && !/^\/local\/(highlights|settings)$/.test(p))
  );
}
