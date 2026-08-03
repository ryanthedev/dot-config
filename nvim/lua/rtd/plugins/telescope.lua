return {
  {
    'nvim-telescope/telescope.nvim',
    commit = '4367e05',
    -- Every telescope keymap in after/plugin/keybindings.lua is a `<cmd>Telescope ...<cr>`
    -- string, so nothing requires the module at startup — the cmd stub is enough.
    cmd = 'Telescope',
    dependencies = {
      'nvim-lua/plenary.nvim',
      -- Must be a dependency, not a sibling spec: config() below calls
      -- load_extension('fzf'), which needs the compiled native lib present.
      { 'nvim-telescope/telescope-fzf-native.nvim', build = 'make' },
    },
    config = function ()
      require('telescope').setup{
        defaults = {
          layout_strategy = 'vertical',
          layout_config = { height = 0.95, width = 0.99 },
          file_ignore_patterns = { "node_modules/", ".git/", "%.lock" },
          hidden = true,
          -- path_display = {
          --   shorten = 2
          -- },
        },
      }

      require('telescope').load_extension('fzf')
    end
  }
}
