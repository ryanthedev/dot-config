-- return {
--   'ellisonleao/gruvbox.nvim',
--   lazy = false,
--   priority = 1000,
--   config = function()
--     require('gruvbox').setup({
--       transparent_mode = true
--     })
--     vim.cmd('colorscheme gruvbox')
--   end,
-- }

-- return {
--   'zootedb0t/citruszest.nvim',
--   lazy = false,
--   priority = 1000,
--   config = function()
--     require("citruszest").setup({})
--     vim.cmd('colorscheme citruszest')
--   end,
-- }
return {
  'ribru17/bamboo.nvim',
  lazy = false,
  priority = 1000,
  config = function()
    require('bamboo').setup {
      -- Main options --
      -- NOTE: to use the light theme, set `vim.o.background = 'light'`
      style = 'multiplex', -- Choose between 'vulgaris' (regular), 'multiplex' (greener), and 'light'
      toggle_style_key = nil, -- Keybind to toggle theme style. Leave it nil to disable it, or set it to a string, e.g. "<leader>ts"
      toggle_style_list = { 'vulgaris', 'multiplex', 'light' }, -- List of styles to toggle between
      transparent = true, -- Show/hide background
      dim_inactive = false, -- Dim inactive windows/buffers
      term_colors = true, -- Change terminal color as per the selected theme style
      ending_tildes = false, -- Show the end-of-buffer tildes. By default they are hidden
      cmp_itemkind_reverse = false, -- reverse item kind highlights in cmp menu

      -- Change code style ---
      -- Options are anything that can be passed to the `vim.api.nvim_set_hl` table
      -- You can also configure styles with a string, e.g. keywords = 'italic,bold'
      code_style = {
        comments = { italic = true, bold = false },
        conditionals = { italic = false },
        keywords = {},
        functions = {},
        namespaces = { italic = true },
        parameters = { italic = false },
        strings = {},
        variables = {},
      },

      -- Lualine options --
      lualine = {
        transparent = false, -- lualine center bar transparency
      },

      -- Custom Highlights --
      colors = {}, -- Override default colors
      highlights = {
        ['LspReferenceRead'] = { fg = '#000'},
        ['@lsp.type.namespace.cs'] = { fg = '#ffffff'},
      }, -- Override highlight groups

      -- Plugins Config --
      diagnostics = {
        darker = false, -- darker colors for diagnostic
        undercurl = true, -- use undercurl instead of underline for diagnostics
        background = true, -- use background color for virtual text
      },
    }
    require('bamboo').load()
    vim.cmd('colorscheme bamboo')
  end,
}
