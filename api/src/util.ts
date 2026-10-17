import { ApiError, type Receipt } from './types.ts';
export function assert(condition: unknown, code: string, message: string, status = 422): asserts condition {
  if (!condition) throw new ApiError(status, code, message);
}
export async function sha256(value: string): Promise<string> {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)))).map(x => x.toString(16).padStart(2, '0')).join('');
}
export function canonical(value: any): string {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value !== null && typeof value === 'object') return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonical(value[k])).join(',') + '}';
  return JSON.stringify(value);
}
export function toBase64(value: string): string {
  return btoa(Array.from(new TextEncoder().encode(value), b => String.fromCharCode(b)).join(''));
}
export function fromBase64(value: string): string {
  return new TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(atob(value), c => c.charCodeAt(0)));
}
export function receiptMarker(receipt: Receipt): string { return `<!-- rsh-receipt:${toBase64(JSON.stringify(receipt))} -->`; }
export function readReceipt(body: string | null): Receipt | null {
  const match = body?.match(/<!-- rsh-receipt:([A-Za-z0-9+/=]+) -->/);
  if (!match) return null;
  try { return JSON.parse(fromBase64(match[1])); } catch { return null; }
}
