return {
  'mhartington/formatter.nvim',
  config = function()
    require('formatter').setup({
      logging = true,
      -- All formatter configurations are opt-in
      filetype = {
        -- Formatter configurations for filetype "lua" go here
        -- and will be executed in order
        lua = {
          -- "formatter.filetypes.lua" defines default configurations for the
          -- "lua" filetype
          require("formatter.filetypes.lua").stylua,
        },
        cs = {
          require'formatter.filetypes.cs'.dotnetformat,
        },
        xml = {
          require('formatter.filetypes.xml').xmllint,
        },
        javascript = {
          require('formatter.filetypes.javascript').prettier,
        },
        json = {
          require('formatter.filetypes.json').prettier,
        },
      },
    })
  end,
}
