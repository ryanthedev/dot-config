return {
  'nvim-treesitter/nvim-treesitter',
  dependencies = {
    {'windwp/nvim-ts-autotag'}
  },
  build = ':TSUpdate',
  config = function()
    require('nvim-treesitter.configs').setup({
      -- enable syntax highlighting
      highlight = {
        enable = true,
      },
      -- enable indentation
      indent = { enable = true },
      -- enable autotagging (w/ nvim-ts-autotag plugin)
      autotag = { enable = true },
      -- ensure these language parsers are installed
      ensure_installed = "all",
      -- auto install above language parsers
      auto_install = true,
    })
    -- -- AutoCmd group for my custom commands.
    -- local gib_autogroup = vim.api.nvim_create_augroup("gib_autogroup", { clear = true })
    --
    -- -- Hide rust imports by default.
    -- -- Refs: https://www.reddit.com/r/neovim/comments/seq0q1/plugin_request_autofolding_file_imports_using/
    -- vim.api.nvim_create_autocmd("FileType",
    -- {
    --   pattern = { "cs" },
    --   callback = function()
    --     print("fold some things")
    --     vim.opt_local.foldlevelstart = 19
    --     vim.opt_local.foldlevel = 19
    --     vim.opt_local.foldexpr =
    --     "v:lnum==1?'>1':getline(v:lnum)=~'^ *using'?20:nvim_treesitter#foldexpr()"
    --   end,
    --   group = gib_autogroup
    -- }
    -- )
  end
}

