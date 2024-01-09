return {
  'nvim-lualine/lualine.nvim',
  dependencies = { 'nvim-tree/nvim-web-devicons' },
  config = function()
    require('lualine').setup({
      options = {
        theme = "citruszest",
      },
      sections = {
        lualine_c = {
          {
            'filename',
            path = 4
          }
        }
      },
      disabled_filetypes = { 'packer', 'NvimTree_1' }
    })
  end
}
