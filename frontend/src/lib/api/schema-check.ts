/**
 * The hand-written API types, held against what the backend says it sends.
 *
 * `schema.d.ts` is generated from the backend's own description of its
 * API (`pnpm gen:api`, from `openapi.json` — kept current by a backend
 * test). `$lib/types` is written by hand and is what the app uses. This
 * file makes the compiler compare the two: for each type both sides
 * have, every field the app expects must be one the backend sends, with
 * a type the app's can hold.
 *
 * It has no runtime content. A line that stops compiling means a field
 * was renamed, removed or retyped on one side only — fix `$lib/types`
 * (or the backend), not this file.
 */
import type * as App from "$lib/types";
import type { components } from "./schema";

type Api = components["schemas"];

/** A field the backend gives a default is optional in its description
 *  and always present in a response: compare as if required. */
type Sent<T> = T extends (infer U)[]
  ? Sent<U>[]
  : T extends object
    ? { [K in keyof T]-?: Sent<T[K]> }
    : T;

/** Compiles only when given `true`. */
type Yes<T extends true> = T;

/** Every field the app's type has is one the backend sends. */
type Named<FromApi, InApp> = [Exclude<keyof InApp, keyof FromApi>] extends [
  never,
]
  ? true
  : false;

/** …and each has a type the app's can hold. */
type Fits<FromApi, InApp> = Sent<FromApi> extends InApp ? true : false;

/** For what the app sends: the backend accepts whatever the app's type
 *  can hold. */
type Accepts<ByApi, FromApp> = FromApp extends ByApi ? true : false;

// Field names: every type both sides have.
// prettier-ignore
export type Fields = [
  Yes<Named<Api["UserOut"], App.UserOut>>,
  Yes<Named<Api["ZhConversionSegment"], App.ZhConversionSegment>>,
  Yes<Named<Api["ZhConversionPreview"], App.ZhConversionPreview>>,
  Yes<Named<Api["LibraryListOut"], App.LibraryOut>>,
  Yes<Named<Api["BookOut"], App.BookOut>>,
  Yes<Named<Api["SeriesOut"], App.SeriesOut>>,
  Yes<Named<Api["PaginatedGrouped"], App.PaginatedGrouped>>,
  Yes<Named<Api["WorkBookBrief"], App.WorkBookBrief>>,
  Yes<Named<Api["WorkOut"], App.WorkOut>>,
  Yes<Named<Api["DuplicateGroup"], App.DuplicateGroup>>,
  Yes<Named<Api["DuplicateSuggestionsOut"], App.DuplicateSuggestionsOut>>,
  Yes<Named<Api["SeriesBookBrief"], App.SeriesBookBrief>>,
  Yes<Named<Api["SeriesProgress"], App.SeriesProgress>>,
  Yes<Named<Api["SeriesNeighborsOut"], App.SeriesNeighborsOut>>,
  Yes<Named<Api["BookWithInteractionOut"], App.BookWithInteractionOut>>,
  Yes<Named<Api["PaginatedBooksWithInteraction"], App.PaginatedBooksWithInteraction>>,
  Yes<Named<Api["BookshelfListOut"], App.BookshelfOut>>,
  Yes<Named<Api["ExternalMetadataOut"], App.ExternalMetadataOut>>,
  Yes<Named<Api["HighlightOut"], App.HighlightOut>>,
  Yes<Named<Api["KosyncMarkerOut"], App.KosyncMarkerOut>>,
  Yes<Named<Api["ProgressOut"], App.ProgressOut>>,
  Yes<Named<Api["HighlightSyncOut"], App.HighlightSyncOut>>,
  Yes<Named<Api["SyncProgressIn"], App.SyncProgressIn>>,
  Yes<Named<Api["SyncInteractionIn"], App.SyncInteractionIn>>,
  Yes<Named<Api["SyncInteractionOut"], App.SyncInteractionOut>>,
  Yes<Named<Api["BookSyncRequest"], App.BookSyncRequest>>,
  Yes<Named<Api["BookSyncResponse"], App.BookSyncResponse>>,
  Yes<Named<Api["MetadataSourceOut"], App.MetadataSourceOut>>,
  Yes<Named<Api["MetadataSourcesOut"], App.MetadataSourcesOut>>,
  Yes<Named<Api["MetadataSourceStats"], App.MetadataSourceStats>>,
  Yes<Named<Api["MetadataSourceStatsOut"], App.MetadataSourceStatsOut>>,
  Yes<Named<Api["MetadataSearchCandidate"], App.MetadataSearchCandidate>>,
  Yes<Named<Api["MetadataSearchOut"], App.MetadataSearchOut>>,
  Yes<Named<Api["IsbnSourceResult"], App.IsbnSourceResult>>,
  Yes<Named<Api["IsbnCoverCandidate"], App.IsbnCoverCandidate>>,
  Yes<Named<Api["IsbnLookupOut"], App.IsbnLookupOut>>,
  Yes<Named<Api["InteractionOut"], App.InteractionOut>>,
  Yes<Named<Api["LoginResponse"], App.LoginResponse>>,
  Yes<Named<Api["IllustrationOut"], App.IllustrationOut>>,
  Yes<Named<Api["StylePromptOut"], App.StylePromptOut>>,
  Yes<Named<Api["ReferenceImageInput"], App.ReferenceImageInput>>,
  Yes<Named<Api["RecapSection"], App.RecapSection>>,
  Yes<Named<Api["RecapOut"], App.RecapOut>>,
  Yes<Named<Api["ApiTokenCreated"], App.ApiTokenCreated>>,
  Yes<Named<Api["CompanionMessageOut"], App.CompanionMessageOut>>,
  Yes<Named<Api["CompanionConversationSummary"], App.CompanionConversationSummary>>,
  Yes<Named<Api["AllJobsResponse"], App.AllJobsResponse>>,
  Yes<Named<Api["CompanionConversationOut"], App.CompanionConversationOut>>,
];

// Field types as well, for what the backend sends. Two are left out,
// each holding a free-form object the backend passes through as stored
// and only the app gives a shape to:
//   ExternalMetadataOut (the archived source record, its reviews)
//   BookSyncResponse (the progress object, verbatim)
// prettier-ignore
export type Types = [
  Yes<Fits<Api["ZhConversionSegment"], App.ZhConversionSegment>>,
  Yes<Fits<Api["ZhConversionPreview"], App.ZhConversionPreview>>,
  Yes<Fits<Api["LibraryListOut"], App.LibraryOut>>,
  Yes<Fits<Api["WorkBookBrief"], App.WorkBookBrief>>,
  Yes<Fits<Api["WorkOut"], App.WorkOut>>,
  Yes<Fits<Api["DuplicateGroup"], App.DuplicateGroup>>,
  Yes<Fits<Api["DuplicateSuggestionsOut"], App.DuplicateSuggestionsOut>>,
  Yes<Fits<Api["SeriesBookBrief"], App.SeriesBookBrief>>,
  Yes<Fits<Api["SeriesProgress"], App.SeriesProgress>>,
  Yes<Fits<Api["SeriesNeighborsOut"], App.SeriesNeighborsOut>>,
  Yes<Fits<Api["BookshelfListOut"], App.BookshelfOut>>,
  Yes<Fits<Api["HighlightOut"], App.HighlightOut>>,
  Yes<Fits<Api["KosyncMarkerOut"], App.KosyncMarkerOut>>,
  Yes<Fits<Api["ProgressOut"], App.ProgressOut>>,
  Yes<Fits<Api["HighlightSyncOut"], App.HighlightSyncOut>>,
  Yes<Fits<Api["MetadataSourceOut"], App.MetadataSourceOut>>,
  Yes<Fits<Api["MetadataSourcesOut"], App.MetadataSourcesOut>>,
  Yes<Fits<Api["MetadataSourceStats"], App.MetadataSourceStats>>,
  Yes<Fits<Api["MetadataSourceStatsOut"], App.MetadataSourceStatsOut>>,
  Yes<Fits<Api["MetadataSearchCandidate"], App.MetadataSearchCandidate>>,
  Yes<Fits<Api["MetadataSearchOut"], App.MetadataSearchOut>>,
  Yes<Fits<Api["IsbnSourceResult"], App.IsbnSourceResult>>,
  Yes<Fits<Api["IsbnCoverCandidate"], App.IsbnCoverCandidate>>,
  Yes<Fits<Api["IsbnLookupOut"], App.IsbnLookupOut>>,
  Yes<Fits<Api["StylePromptOut"], App.StylePromptOut>>,
  Yes<Fits<Api["ReferenceImageInput"], App.ReferenceImageInput>>,
  Yes<Fits<Api["RecapSection"], App.RecapSection>>,
  Yes<Fits<Api["RecapOut"], App.RecapOut>>,
  Yes<Fits<Api["ApiTokenCreated"], App.ApiTokenCreated>>,
  Yes<Fits<Api["CompanionConversationSummary"], App.CompanionConversationSummary>>,
  Yes<Fits<Api["AllJobsResponse"], App.AllJobsResponse>>,
  Yes<Fits<Api["UserOut"], App.UserOut>>,
  Yes<Fits<Api["BookOut"], App.BookOut>>,
  Yes<Fits<Api["SeriesOut"], App.SeriesOut>>,
  Yes<Fits<(Api["GroupedSeries"] | Api["GroupedBook"]), App.GroupedItem>>,
  Yes<Fits<Api["PaginatedGrouped"], App.PaginatedGrouped>>,
  Yes<Fits<Api["BookWithInteractionOut"], App.BookWithInteractionOut>>,
  Yes<Fits<Api["PaginatedBooksWithInteraction"], App.PaginatedBooksWithInteraction>>,
  Yes<Fits<Api["SyncInteractionOut"], App.SyncInteractionOut>>,
  Yes<Fits<Api["InteractionOut"], App.InteractionOut>>,
  Yes<Fits<Api["LoginResponse"], App.LoginResponse>>,
  Yes<Fits<Api["IllustrationOut"], App.IllustrationOut>>,
  Yes<Fits<Api["CompanionMessageOut"], App.CompanionMessageOut>>,
  Yes<Fits<Api["CompanionConversationOut"], App.CompanionConversationOut>>,
];

// …and for what the app sends, the other way round.
// prettier-ignore
export type Requests = [
  Yes<Accepts<Api["SyncProgressIn"], App.SyncProgressIn>>,
  Yes<Accepts<Api["SyncInteractionIn"], App.SyncInteractionIn>>,
  Yes<Accepts<Api["BookSyncRequest"], App.BookSyncRequest>>,
  Yes<Accepts<Api["ReferenceImageInput"], App.ReferenceImageInput>>,
];
