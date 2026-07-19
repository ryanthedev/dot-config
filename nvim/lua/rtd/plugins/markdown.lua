return {
  'MeanderingProgrammer/render-markdown.nvim',
  dependencies = { 'nvim-treesitter/nvim-treesitter', 'nvim-tree/nvim-web-devicons' }, -- if you prefer nvim-web-devicons
  ---@module 'render-markdown'
  ---@type render.md.UserConfig
  opts = {
    -- Keep the whole buffer rendered in Normal mode. By default render-markdown
    -- "anti-conceals" the cursor's line (shows raw markdown there), which flips
    -- line-to-line as you navigate — the jarring shift. Disabling it keeps every
    -- line rendered in Normal mode. Raw source still appears in Insert mode,
    -- because Insert ('i') is not in render_modes (default { 'n', 'c', 't' }).
    anti_conceal = { enabled = false },
    -- Draw a thin rule line above and below each heading (keeps the per-level
    -- background bar). Uses '▄' above and '▀' below. If a heading isn't
    -- surrounded by blank lines and the borders look off, set
    -- `border_virtual = true` to always use virtual lines instead.
    heading = { border = true },
    -- Let snacks.image own ```mermaid blocks. render-markdown's code-block
    -- decoration (the "m mermaid" language label, background, delimiter
    -- conceal) competes with snacks' inline image overlay and clips the
    -- rendered diagram. Disabling render-markdown for mermaid gives snacks the
    -- whole block, so the diagram paints uncut.
    code = { disable = { 'mermaid' } },
  },
  ft = { "markdown", "codecompanion" }
}
