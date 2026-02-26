return  {
	{
		'alexghergh/nvim-tmux-navigation',
		config = function()
			require('nvim-tmux-navigation').setup({
				disable_when_zoomed = true, -- defaults to false
				keybindings = {
					left = '<C-h>',
					down = '<C-j>',
					up = '<C-k>',
					right = '<C-l>',
					last_active = '<C-b>',
					next = '<C-n>',
				},
			})
		end,
	},
  -- ANSI color rendering for scrollback viewer
  {
    'm00qek/baleia.nvim',
    version = '*',
    config = function()
      vim.g.baleia = require('baleia').setup({
        async = true,
        chunk_size = 2000,
      })
      vim.api.nvim_create_user_command('BaleiaColorize', function()
        vim.g.baleia.once(vim.api.nvim_get_current_buf())
      end, { bang = true })
    end,
  }
}
