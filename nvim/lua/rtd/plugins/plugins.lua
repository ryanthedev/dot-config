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
	-- DAP
	{
		'rcarriga/nvim-dap-ui',
		dependencies = { 'mfussenegger/nvim-dap' },
	},
  {
    'jayp0521/mason-nvim-dap.nvim',
  },
  {
    'nvim-telescope/telescope-dap.nvim',
  },
  -- Meow
  {
    'fladson/vim-kitty',
  }
}
