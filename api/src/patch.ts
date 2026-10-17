import { assert } from './util.ts';
type Hunk = { oldStart: number; oldCount: number; newStart: number; newCount: number; lines: { kind: string; text: string }[] };
export interface FilePatch { path: string; hunks: Hunk[] }
function safePath(path: string): boolean {
  return /^[A-Za-z0-9][A-Za-z0-9._/-]*$/.test(path) && !path.split('/').some(p => p === '.' || p === '..' || p === '') && !path.startsWith('.');
}
export function parsePatch(patch: string): FilePatch[] {
  assert(patch.length > 0 && !patch.includes('\0'), 'invalid_patch', 'A nonempty text unified diff is required.');
  const lines = patch.match(/[^\n]*\n|[^\n]+$/g) || [];
  const files: FilePatch[] = []; let i = 0;
  const clean = (line: string) => line.replace(/\n$/, '');
  while (i < lines.length) {
    if (lines[i].startsWith('diff --git ')) {
      assert(/^diff --git a\/[^ ]+ b\/[^ ]+\n?$/.test(lines[i]), 'invalid_patch', 'Unsupported diff header.'); i++;
      if (lines[i]?.startsWith('index ')) { assert(/^index [a-f0-9]+\.\.[a-f0-9]+(?: 100644)?\n?$/.test(lines[i]), 'invalid_patch', 'Only regular text files may be changed.'); i++; }
    }
    assert(lines[i]?.startsWith('--- a/') && lines[i + 1]?.startsWith('+++ b/'), 'invalid_patch', 'Only modifications of existing regular files are supported.');
    const path = clean(lines[i]).slice(6); const target = clean(lines[i + 1]).slice(6); i += 2;
    assert(path === target && safePath(path), 'invalid_path', 'Renames, traversal, creation and deletion are not allowed.');
    assert(!files.some(f => f.path === path) && files.length < 8, 'invalid_patch', 'Each file may appear once; at most eight files.');
    const file: FilePatch = { path, hunks: [] };
    while (i < lines.length && lines[i].startsWith('@@ ')) {
      const m = clean(lines[i++]).match(/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$/);
      assert(m, 'invalid_patch', 'Invalid hunk header.');
      const hunk: Hunk = { oldStart: +m[1], oldCount: m[2] === undefined ? 1 : +m[2], newStart: +m[3], newCount: m[4] === undefined ? 1 : +m[4], lines: [] };
      let oldCount = 0; let newCount = 0;
      while (i < lines.length && !lines[i].startsWith('@@ ') && !lines[i].startsWith('--- a/') && !lines[i].startsWith('diff --git ')) {
        const line = lines[i++];
        if (line.startsWith('\\ No newline at end of file')) {
          assert(clean(line) === '\\ No newline at end of file' && hunk.lines.length, 'invalid_patch', 'Invalid newline marker.');
          const last = hunk.lines[hunk.lines.length - 1];
          assert(last.text.endsWith('\n'), 'invalid_patch', 'Duplicate newline marker.'); last.text = last.text.slice(0, -1); continue;
        }
        const kind = line[0];
        assert([' ', '-', '+'].includes(kind), 'invalid_patch', 'Unsupported unified diff line.');
        if (kind !== '+') oldCount++; if (kind !== '-') newCount++;
        assert(oldCount <= hunk.oldCount && newCount <= hunk.newCount, 'invalid_patch', 'Hunk line count mismatch.');
        hunk.lines.push({ kind, text: line.slice(1) });
      }
      assert(oldCount === hunk.oldCount && newCount === hunk.newCount, 'invalid_patch', 'Hunk line count mismatch.');
      file.hunks.push(hunk);
    }
    assert(file.hunks.length > 0, 'invalid_patch', 'A file needs at least one hunk.'); files.push(file);
  }
  assert(files.length > 0 && files.some(f => f.hunks.some(h => h.lines.some(l => l.kind !== ' '))), 'no_changes', 'No changed lines.');
  return files;
}
export function applyPatch(original: string, file: FilePatch): string {
  const source = original.match(/[^\n]*\n|[^\n]+$/g) || [];
  const output: string[] = []; let cursor = 0;
  for (const hunk of file.hunks) {
    const start = hunk.oldCount === 0 ? hunk.oldStart : hunk.oldStart - 1;
    assert(start >= cursor && start <= source.length, 'patch_context_mismatch', 'Hunks must be ordered and within the base file.');
    output.push(...source.slice(cursor, start)); cursor = start;
    const expectedNew = hunk.newCount === 0 ? hunk.newStart : hunk.newStart - 1;
    assert(output.length === expectedNew, 'invalid_patch', 'New hunk coordinates do not match.');
    for (const line of hunk.lines) {
      if (line.kind !== '+') { assert(source[cursor] === line.text, 'patch_context_mismatch', `Patch context differs in ${file.path}.`); cursor++; }
      if (line.kind !== '-') output.push(line.text);
    }
  }
  output.push(...source.slice(cursor)); const result = output.join('');
  assert(result !== original, 'no_changes', 'Patch does not change the base file.');
  assert(new TextEncoder().encode(result).length <= 128 * 1024, 'file_too_large', 'Changed file exceeds 128 KiB.');
  return result;
}
