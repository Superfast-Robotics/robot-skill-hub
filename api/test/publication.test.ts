import test from 'node:test';
import assert from 'node:assert/strict';
import { readPublication } from '../src/publication.ts';

test('publication proof limits UTF-8 bytes rather than decoded character count', async () => {
  const text = JSON.stringify({ note: 'éééé' });
  const bytes = new TextEncoder().encode(text).byteLength;
  assert.ok(bytes > text.length);
  assert.deepEqual(await readPublication(new Response(text), bytes), { note: 'éééé' });
  await assert.rejects(readPublication(new Response(text), bytes - 1), /too large/);
});

test('oversized streaming publication is cancelled before buffering the remainder', async () => {
  let cancelled = false, pulls = 0;
  const body = new ReadableStream<Uint8Array>({
    pull(controller) { pulls++; controller.enqueue(new Uint8Array(8)); },
    cancel() { cancelled = true; }
  });
  await assert.rejects(readPublication(new Response(body), 9), /too large/);
  assert.equal(cancelled, true);
  assert.ok(pulls <= 3);
});

test('declared oversize, HTTP failure and malformed UTF-8 never become publication proof', async () => {
  await assert.rejects(readPublication(new Response('{}', { headers: { 'Content-Length': '100' } }), 10), /too large/);
  await assert.rejects(readPublication(new Response('{}', { status: 503 })), /unavailable/);
  await assert.rejects(readPublication(new Response(new Uint8Array([0xff]))));
  await assert.rejects(readPublication(new Response('{')));
});
