/** Basic discovery grammar; native unicode61 additionally has its own case/accent rules. */
export function wordTerms(value: string): string[] {
  return value.toLowerCase().match(/[\p{L}\p{N}]+/gu) || [];
}

export function containsWordPrefixes(value: string, terms: readonly string[]): boolean {
  const words = wordTerms(value);
  return terms.every(term => words.some(word => word.startsWith(term)));
}
