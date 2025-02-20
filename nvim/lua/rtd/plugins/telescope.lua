return {
  {
    'nvim-telescope/telescope-fzf-native.nvim',
    build = 'make'
  },
  {
    'nvim-telescope/telescope.nvim',
    commit = '4367e05',
    dependencies = { 'nvim-lua/plenary.nvim' },
    config = function ()
      require('telescope').setup{
        defaults = {
          layout_strategy = 'vertical',
          layout_config = { height = 0.95, width = 0.99 },
          -- path_display = {
          --   shorten = 2
          -- },
        },
      }

      require('telescope').load_extension('fzf')
    end
  }
}
