/** One hit of a whole-book search: where it is and the text around it. */
export interface SearchResult {
  cfi: string;
  excerpt: string;
  sectionLabel: string;
  sectionIndex: number;
}
