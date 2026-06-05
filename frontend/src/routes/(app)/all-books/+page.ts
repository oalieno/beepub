import { redirect } from "@sveltejs/kit";
import type { PageLoad } from "./$types";

// "All books" merged into the unified library page as the default selection.
export const load: PageLoad = ({ url }) => {
  const sp = new URLSearchParams(url.search);
  const qs = sp.toString();
  throw redirect(308, qs ? `/libraries?${qs}` : "/libraries");
};
