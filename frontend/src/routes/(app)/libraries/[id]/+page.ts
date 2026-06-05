import { redirect } from "@sveltejs/kit";
import type { PageLoad } from "./$types";

// Per-library page folded into the unified /libraries page (selected via ?lib).
export const load: PageLoad = ({ params, url }) => {
  const sp = new URLSearchParams(url.search);
  sp.set("lib", params.id);
  throw redirect(308, `/libraries?${sp.toString()}`);
};
