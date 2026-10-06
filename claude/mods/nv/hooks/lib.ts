// Pure helpers for /nv and /yank, kept apart from `$` so tests can call them.

export type Target = { path: string; line?: number }

/** One nvim per Claude pane, so two Claude sessions never share an editor. */
export const sockPath = (paneId: string): string =>
  `/tmp/claude-nv-${paneId.replace(/[^A-Za-z0-9]/g, '_')}.sock`

/** POSIX single-quoting, for the one string herdr types into a fresh shell. */
export const shellQuote = (s: string): string => `'${s.replaceAll("'", `'\\''`)}'`

/** A Vim single-quoted string literal: the only escape is '' for '. */
export const vimString = (s: string): string => `'${s.replaceAll("'", "''")}'`

/**
 * Reads `/nv` args as one path (spaces allowed), an optional `:line` suffix,
 * and optional surrounding quotes. Relative paths resolve against `cwd`.
 */
export const parseTarget = (args: string, cwd: string, home: string): Target | undefined => {
  let raw = args.trim()
  if (raw === '' || raw.includes('\n')) return undefined
  let line: number | undefined
  const withLine = /^(.*):(\d+)$/.exec(raw)
  if (withLine) {
    raw = withLine[1] ?? ''
    line = Number(withLine[2])
  }
  const quoted = /^(['"])(.*)\1$/.exec(raw)
  if (quoted) raw = quoted[2] ?? ''
  if (raw === '') return undefined
  const path =
    raw.startsWith('/') ? raw
    : raw === '~' ? home
    : raw.startsWith('~/') ? `${home}/${raw.slice(2)}`
    : `${cwd}/${raw}`
  return { path, line }
}

/** The text of the nth-newest assistant message that has any text. */
export const pickReply = (
  messages: readonly { role: string; text: string }[],
  back: number,
): string | undefined => {
  const replies = messages.filter(m => m.role === 'assistant' && m.text.trim() !== '')
  return replies.at(-Math.max(1, back))?.text
}

/** The Vim expression that opens a target in a running nvim, reusing its tab if open. */
export const remoteOpenExpr = (t: Target): string => {
  const cmds = [`'tab drop ' . fnameescape(${vimString(t.path)})`]
  if (t.line !== undefined) cmds.push(vimString(String(t.line)))
  return `execute([${cmds.join(', ')}])`
}

/** The shell line typed into a fresh herdr split to start a listening nvim. */
export const launchLine = (sock: string, t: Target | undefined): string => {
  const argv = ['nvim', '--listen', sock]
  if (t?.line !== undefined) argv.push(`+${t.line}`)
  if (t) argv.push('--', t.path)
  return argv.map(shellQuote).join(' ')
}
