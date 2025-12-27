return {
  'nvim-treesitter/nvim-treesitter',
  dependencies = {
    {'windwp/nvim-ts-autotag'}
  },
  build = ':TSUpdate',
  config = function()
    require('nvim-treesitter.configs').setup({
      highlight = { enable = true },
      indent = { enable = true },
      autotag = { enable = true },
      -- Install only languages you use (faster updates, less disk usage)
      ensure_installed = {
        "bash", "c", "c_sharp", "css", "diff", "dockerfile",
        "go", "gomod", "gosum", "html", "javascript", "json", "jsonc",
        "lua", "luadoc", "markdown", "markdown_inline", "python",
        "query", "regex", "rust", "swift", "toml", "tsx", "typescript",
        "vim", "vimdoc", "xml", "yaml",
      },
      auto_install = true,
    })
  end
}
