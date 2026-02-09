return {
  'nvim-treesitter/nvim-treesitter',
  lazy = false,
  dependencies = {
    {'windwp/nvim-ts-autotag'}
  },
  build = ':TSUpdate',
  config = function()
    require('nvim-treesitter').setup {}

    -- Install parsers
    require('nvim-treesitter').install {
      "bash", "c", "c_sharp", "css", "diff", "dockerfile",
      "go", "gomod", "gosum", "html", "javascript", "json",
      "lua", "luadoc", "markdown", "markdown_inline", "python",
      "query", "regex", "rust", "swift", "toml", "tsx", "typescript",
      "vim", "vimdoc", "xml", "yaml",
    }

    -- Enable treesitter highlighting for all filetypes
    vim.api.nvim_create_autocmd('FileType', {
      callback = function()
        pcall(vim.treesitter.start)
      end,
    })

    require('nvim-ts-autotag').setup()
  end
}
