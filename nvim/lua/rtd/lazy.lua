require('lazy').setup({
	-- Telescope
  {
    'nvim-telescope/telescope.nvim', tag = '0.1.5',
    dependencies = { 'nvim-lua/plenary.nvim' }
  },

	-- the poon
	{
		'ThePrimeagen/harpoon',
		branch = 'harpoon2',
		dependencies =  { 'nvim-lua/plenary.nvim' },
	},

	-- Da line
	{
    'nvim-lualine/lualine.nvim',
    dependencies = { 'nvim-tree/nvim-web-devicons' }
  },

  -- Theme
  {
		'zootedb0t/citruszest.nvim',
    lazy = false,
    priority = 1000,
  },
	-- -- Dashboard
  { 
    'goolord/alpha-nvim',
    dependencies = { 'nvim-tree/nvim-web-devicons' },
    priority = 1001,
  },
	-- Treesitter
	{
		'nvim-treesitter/nvim-treesitter',
		build = ':TSUpdate',
	},
	-- -- nvim tree
  {
    'nvim-tree/nvim-tree.lua',
    version = '*',
    lazy = false,
    dependencies = {
      'nvim-tree/nvim-web-devicons',
      }
  },
	{ 
    'williamboman/mason.nvim' 
  },
	{ 
    'williamboman/mason-lspconfig.nvim' 
  },
	{
		'VonHeikemen/lsp-zero.nvim',
		branch = 'v3.x',
		lazy = true,
		config = false,
		init = function()
			-- Disable automatic setup, we are doing it manually
			vim.g.lsp_zero_extend_cmp = 0
			vim.g.lsp_zero_extend_lspconfig = 0
		end,
	},
	-- LSP Support
	{ 
    'neovim/nvim-lspconfig' 
  },
	-- Autocompletion
	{ 
    'hrsh7th/nvim-cmp' 
  },
	{
    'hrsh7th/cmp-nvim-lsp' 
  },
  { 
    'L3MON4D3/LuaSnip'
  },
	{
    'hrsh7th/cmp-nvim-lsp-signature-help'
  },
	{
    'j-hui/fidget.nvim'
  },
	-- dotnet lsp thangs
	{
    'jmederosalvarado/roslyn.nvim'
  },

	{
		'folke/trouble.nvim',
		dependencies = {
			{ 'nvim-tree/nvim-web-devicons' },
		},
	},
	-- Mason recommended linter
  {
    'mfussenegger/nvim-lint',
  },
	-- Mason recommended formatter
  {
    'mhartington/formatter.nvim'
  },
	-- Autoclose
  {
    'm4xshen/autoclose.nvim'
  },
	-- -- Comment
	{
		'numToStr/Comment.nvim',
    lazy = false,
	},
	-- -- Text wrapping
	-- {
	-- 	'andrewferrier/wrapping.nvim',
	-- 	config = function()
	-- 		require('wrapping').setup({ create_keymaps = false })
	-- 	end,
	-- },
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
					last_active = '<C-Backspace>',
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
})
