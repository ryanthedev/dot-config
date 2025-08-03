return {
  'stevearc/oil.nvim',
  ---@module 'oil'
  ---@type oil.SetupOpts
  opts = {},
  -- Optional dependencies
  dependencies = { { "echasnovski/mini.icons", opts = {} } },
  -- Lazy loading is not recommended because it is very tricky to make it work correctly in all situations.
  lazy = false,
  config = function()
    require('oil').setup({
        view_options = {
          -- Show files and directories that start with "."
          show_hidden = true,
          -- This function defines what is considered a "hidden" file
          is_hidden_file = function(name, bufnr)
            return false -- Don't hide any files
          end,
          -- This function defines what files should always be shown
          is_always_hidden = function(name, bufnr)
            return false -- Don't hide any files
          end,
        },
        -- Don't use .gitignore to hide files
        use_default_keymaps = true,
        skip_confirm_for_simple_edits = false,
    })
  end
}
