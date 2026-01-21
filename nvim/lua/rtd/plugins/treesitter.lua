return {
  'nvim-treesitter/nvim-treesitter',
  dependencies = {
    {'windwp/nvim-ts-autotag'}
  },
  build = ':TSUpdate',
  opts = {
    ensure_installed = {
      "bash", "c", "c_sharp", "css", "diff", "dockerfile",
      "go", "gomod", "gosum", "html", "javascript", "json",
      "lua", "luadoc", "markdown", "markdown_inline", "python",
      "query", "regex", "rust", "swift", "toml", "tsx", "typescript",
      "vim", "vimdoc", "xml", "yaml",
    },
    highlight = { enable = true },
    indent = { enable = true },
  },
  config = function(_, opts)
    require('nvim-treesitter').setup(opts)
    require('nvim-ts-autotag').setup()
  end
}
