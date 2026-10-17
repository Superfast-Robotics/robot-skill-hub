/** Basic discovery grammar; native unicode61 additionally has its own case/accent rules. */
export function wordTerms(value: string): string[] {
  return value.toLowerCase().match(/[\p{L}\p{N}]+/gu) || [];
}

/** Query-only spelling for canonical algorithm literals, never document tokens.
 * Keep identifiers and repeated stars in the existing word-prefix grammar.
 */
export function queryTerms(value: string): string[] {
  const normalized = value.replace(/(?<![\p{L}\p{N}\p{M}_*])(rrt|[ad])\*(?![\p{L}\p{N}\p{M}_*])/giu,
    (_, algorithm: string) => algorithm.toLowerCase() + 'star');
  return wordTerms(normalized);
}

export function containsWordPrefixes(value: string, terms: readonly string[]): boolean {
  const words = wordTerms(value);
  return terms.every(term => words.some(word => word.startsWith(term)));
}
