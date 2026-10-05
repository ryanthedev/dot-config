import type { Register } from 'claude-code'

// The module's environment may not share the host's time zone, so the
// offset comes from the host's own `date` once per load.
const offsetMs = async (run: (argv: readonly string[]) => Promise<{ exitCode: number; stdout: string }>) => {
  try {
    const { exitCode, stdout } = await run(['date', '+%z'])
    const m = /^([+-])(\d{2})(\d{2})/.exec(stdout.trim())
    if (exitCode !== 0 || !m) return 0
    const sign = m[1] === '-' ? -1 : 1
    return sign * (Number(m[2]) * 60 + Number(m[3])) * 60_000
  } catch {
    return 0
  }
}

export const format = (epochMs: number, offset: number) => {
  const d = new Date(epochMs + offset)
  const hh = String(d.getUTCHours()).padStart(2, '0')
  const mm = String(d.getUTCMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    if (!e.isInteractive) return started

    // Re-read hourly so a DST change or a new time zone shows up without a reload.
    let offset = await offsetMs(argv => $.process.run(argv))
    let offsetReadAt = await $.clock.now()
    let shown = ''
    const tick = async () => {
      const now = await $.clock.now()
      if (now - offsetReadAt >= 3_600_000) {
        offset = await offsetMs(argv => $.process.run(argv))
        offsetReadAt = now
      }
      const text = format(now, offset)
      if (text === shown) return
      shown = text
      $.ui.status(text)
    }

    await tick()
    $.clock.every(5_000, () => void tick())

    return started
  })
}
