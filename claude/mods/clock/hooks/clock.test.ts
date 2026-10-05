import { test, expect } from 'claude-code/testing'
import { format } from './register'

test('formats local HH:MM from epoch and offset', () => {
  // 2026-10-03 21:05 UTC
  const t = Date.UTC(2026, 9, 3, 21, 5)
  expect(format(t, 0)).toBe('21:05')
  expect(format(t, -5 * 3_600_000)).toBe('16:05')
  expect(format(t, 5.5 * 3_600_000)).toBe('02:35')
})
