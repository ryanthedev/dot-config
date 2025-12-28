return {
  'nvim-treesitter/nvim-treesitter',
  dependencies = {
    {'windwp/nvim-ts-autotag'}
  },
  build = ':TSUpdate',
  config = function()
    local ts = require('nvim-treesitter')

    -- Install parsers
    ts.install {
      "bash", "c", "c_sharp", "css", "diff", "dockerfile",
      "go", "gomod", "gosum", "html", "javascript", "json",
      "lua", "luadoc", "markdown", "markdown_inline", "python",
      "query", "regex", "rust", "swift", "toml", "tsx", "typescript",
      "vim", "vimdoc", "xml", "yaml",
    }

    -- Enable highlighting and indentation for all buffers
    vim.api.nvim_create_autocmd("FileType", {
      callback = function()
        pcall(vim.treesitter.start)
        vim.bo.indentexpr = "v:lua.require'nvim-treesitter'.indentexpr()"
      end,
    })

    -- Configure autotag
    require('nvim-ts-autotag').setup()
  end
}
