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
        keymaps = {
          ["gy"] = {
            callback = function()
              local oil = require("oil")
              local entry = oil.get_cursor_entry()
              local dir = oil.get_current_dir()
              if entry and dir then
                local path = dir .. entry.name
                vim.fn.setreg("+", path)
                vim.notify("Copied: " .. path)
              end
            end,
            desc = "Copy absolute path",
          },
        },
        use_default_keymaps = true,
        skip_confirm_for_simple_edits = false,
    })
  end
}
