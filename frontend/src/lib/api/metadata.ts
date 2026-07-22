import { get } from "./client";
import type { MetadataSourcesOut, MetadataSourceStatsOut } from "$lib/types";

export const metadataApi = {
  getSources: () => get("/metadata/sources") as Promise<MetadataSourcesOut>,
  getSourceStats: () =>
    get("/metadata/sources/stats") as Promise<MetadataSourceStatsOut>,
};
