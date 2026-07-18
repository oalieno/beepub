import { get } from "./client";
import type { MetadataSourcesOut } from "$lib/types";

export const metadataApi = {
  getSources: () => get("/metadata/sources") as Promise<MetadataSourcesOut>,
};
