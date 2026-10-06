import { test, expect } from 'claude-code/testing'
import { launchLine, parseTarget, pickReply, privateDir, remoteOpenExpr, shellQuote, sockPath } from './lib'

test('one socket per herdr pane, safe characters only', () => {
  expect(sockPath('/private/T', 'w1Y:pW')).toBe('/private/T/claude-nv-w1Y_pW.sock')
})

test('temp files go in the per-user folder, never the shared /tmp', () => {
  expect(privateDir('/var/folders/dy/abc/T/', '/Users/r')).toBe('/var/folders/dy/abc/T')
  expect(privateDir(undefined, '/Users/r')).toBe('/Users/r/.cache/claude-nv')
})

test('parses paths, ~, :line and quotes', () => {
  expect(parseTarget('src/a.ts', '/repo', '/home')).toEqual({ path: '/repo/src/a.ts', line: undefined })
  expect(parseTarget('src/a.ts:42', '/repo', '/home')).toEqual({ path: '/repo/src/a.ts', line: 42 })
  expect(parseTarget('~/notes.md', '/repo', '/home')).toEqual({ path: '/home/notes.md', line: undefined })
  expect(parseTarget('"my file.ts"', '/repo', '/home')).toEqual({ path: '/repo/my file.ts', line: undefined })
  expect(parseTarget('/abs/x', '/repo', '/home')?.path).toBe('/abs/x')
  expect(parseTarget('  ', '/repo', '/home')).toBeUndefined()
})

test('picks the nth-newest assistant reply with text', () => {
  const msgs = [
    { role: 'assistant', text: 'first' },
    { role: 'user', text: 'q' },
    { role: 'assistant', text: 'second' },
    { role: 'assistant', text: '' },
  ]
  expect(pickReply(msgs, 1)).toBe('second')
  expect(pickReply(msgs, 2)).toBe('first')
  expect(pickReply(msgs, 3)).toBeUndefined()
})

test('shell line survives hostile filenames', () => {
  expect(shellQuote("it's $(rm -rf ~)")).toBe(`'it'\\''s $(rm -rf ~)'`)
  expect(launchLine('/tmp/s.sock', { path: '/r/a b.ts', line: 3 }))
    .toBe(`'nvim' '--listen' '/tmp/s.sock' '+3' '--' '/r/a b.ts'`)
  expect(launchLine('/tmp/s.sock', undefined)).toBe(`'nvim' '--listen' '/tmp/s.sock'`)
})

test('remote open escapes quotes for Vim', () => {
  expect(remoteOpenExpr({ path: "/r/it's.md", line: 7 }))
    .toBe(`execute(['tab drop ' . fnameescape('/r/it''s.md'), '7'])`)
})
