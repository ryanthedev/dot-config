return {
  'nvim-telescope/telescope.nvim',
  tag = '0.1.6',
  dependencies = { 'nvim-lua/plenary.nvim' },
  config = function ()
    require('telescope').setup{
      defaults = {
        layout_strategy = 'vertical',
        layout_config = { height = 0.95, width = 0.99 },
      },
    }
  end
}
