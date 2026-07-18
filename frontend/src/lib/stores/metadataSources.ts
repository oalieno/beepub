import { metadataApi } from "$lib/api/metadata";
import type { MetadataSourceOut } from "$lib/types";

// The plugin registry is static per backend process — fetch once per
// session and share across consumers (ExternalRatings, admin pages).
let cache: Promise<MetadataSourceOut[]> | null = null;

export function getMetadataSources(): Promise<MetadataSourceOut[]> {
  cache ??= metadataApi
    .getSources()
    .then((response) => response.sources)
    .catch((error) => {
      cache = null; // allow a retry on the next call
      throw error;
    });
  return cache;
}

export function invalidateMetadataSources(): void {
  cache = null;
}
