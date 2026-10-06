import type { CommandRunInput, EngineInterface, Register } from 'claude-code'

import { launchLine, parseTarget, pickReply, privateDir, remoteOpenExpr, sockPath, type Target } from './lib'

// Only the person at this Mac may open panes on it: a phone (bridge) or
// another agent running /nv would split a terminal nobody is looking at.
const LOCAL_ORIGINS = new Set(['composer', 'unclassified'])

const refusal = (e: CommandRunInput): string | undefined =>
  LOCAL_ORIGINS.has(e.origin.kind)
    ? undefined
    : `/${e.command} only runs from the Mac terminal (this came from ${e.origin.kind}).`

const run = async ($: EngineInterface, argv: readonly string[]) => {
  try {
    return await $.process.run(argv)
  } catch (err) {
    return { exitCode: -1, stdout: '', stderr: String(err) }
  }
}

// `pane split` answers the new pane first; `pane neighbor` answers the whole
// layout, so its neighbor sits under its own key.
const tempDir = async ($: EngineInterface) =>
  privateDir(await $.env.get('TMPDIR'), (await $.env.get('HOME')) ?? '')

const paneIdOf = (json: string): string | undefined => /"pane_id":"([^"]+)"/.exec(json)?.[1]
const neighborIdOf = (json: string): string | undefined => /"neighbor_pane_id":"([^"]+)"/.exec(json)?.[1]

/**
 * Opens `target` (or just an empty editor) in this Claude pane's nvim,
 * starting one in a new herdr split to the right when none is listening.
 * Answers the line the command shows.
 */
const openInNvim = async ($: EngineInterface, target: Target | undefined, label: string) => {
  const claudePane = await $.env.get('HERDR_PANE_ID')
  if (!claudePane) return 'Not running inside a herdr pane, so there is nowhere to open nvim.'
  const sock = sockPath(await tempDir($), claudePane)

  const alive = await run($, ['nvim', '--server', sock, '--remote-expr', '1'])
  if (alive.exitCode === 0) {
    if (target) {
      const opened = await run($, ['nvim', '--server', sock, '--remote-expr', remoteOpenExpr(target)])
      if (opened.exitCode !== 0) return `nvim refused to open ${label}: ${opened.stderr.trim()}`
    }
    // Focus it only when it is the pane right of Claude, the one /nv made.
    const nvimPane = (await run($, ['nvim', '--server', sock, '--remote-expr', '$HERDR_PANE_ID'])).stdout.trim()
    const right = neighborIdOf((await run($, ['herdr', 'pane', 'neighbor', '--pane', claudePane, '--direction', 'right'])).stdout)
    if (nvimPane && nvimPane === right) {
      await run($, ['herdr', 'pane', 'focus', '--pane', claudePane, '--direction', 'right'])
    }
    return `Opened ${label} in nvim.`
  }

  // No nvim answers: clear a socket a dead nvim left behind, or --listen fails.
  await run($, ['rm', '-f', sock])
  await run($, ['mkdir', '-p', '-m', '700', sock.slice(0, sock.lastIndexOf('/'))])
  const cwd = await $.session.cwd()
  const split = await run($, ['herdr', 'pane', 'split', claudePane, '--direction', 'right', '--focus', '--cwd', cwd])
  const nvimPane = paneIdOf(split.stdout)
  if (split.exitCode !== 0 || !nvimPane) return `herdr could not split the pane: ${split.stderr.trim() || split.stdout.trim()}`
  // `pane run` types into the pane's shell; the split is brand new, so that
  // shell is idle, and launchLine quotes every argument.
  const started = await run($, ['herdr', 'pane', 'run', nvimPane, launchLine(sock, target)])
  if (started.exitCode !== 0) return `herdr could not start nvim: ${started.stderr.trim()}`
  return `Opened ${label} in nvim in a new split.`
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'nv',
      description: 'Open a file in nvim in a herdr split beside Claude (/nv path[:line])',
    })
    await $.command.register({
      name: 'yank',
      description: "Open Claude's last reply in the nvim split to copy from it (/yank [n] for n replies back)",
    })
    return next(e)
  })

  on('command.run', { command: 'nv' }, async ($, e) => {
    const refused = refusal(e)
    if (refused) return { text: refused }
    const home = (await $.env.get('HOME')) ?? ''
    const target = parseTarget(e.args, await $.session.cwd(), home)
    return { text: await openInNvim($, target, target ? target.path : 'nvim') }
  })

  on('command.run', { command: 'yank' }, async ($, e) => {
    const refused = refusal(e)
    if (refused) return { text: refused }
    const arg = e.args.trim()
    if (arg !== '' && !/^\d+$/.test(arg)) return { text: 'Usage: /yank [n], where n counts replies back (1 is the last).' }
    const back = arg === '' ? 1 : Number(arg)

    const reply = pickReply(await $.session.messages(), back)
    if (reply === undefined) return { text: `There is no reply ${back} back to yank.` }

    const path = `${await tempDir($)}/claude-yank/${await $.clock.now()}.md`
    await $.fs.write(path, reply)
    const label = back === 1 ? 'the last reply' : `the reply ${back} back`
    return { text: await openInNvim($, { path }, label) }
  })
}
