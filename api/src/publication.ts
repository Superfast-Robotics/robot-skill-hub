/** Read publication proof with a streaming UTF-8 byte bound. */
export async function readPublication(response: Response, maximum = 512 * 1024): Promise<unknown> {
  if (!response.ok || Number(response.headers.get('Content-Length')) > maximum) {
    await response.body?.cancel();
    throw new Error('Publication unavailable or too large');
  }
  const reader = response.body?.getReader();
  if (!reader) throw new Error('Publication has no body');
  let length = 0;
  const chunks: Uint8Array[] = [];
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > maximum) {
        await reader.cancel();
        throw new Error('Publication too large');
      }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
}
