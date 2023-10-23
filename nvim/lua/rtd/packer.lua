return require("packer").startup(function(use)
  use("wbthomason/packer.nvim")

  -- Telescope
  use("nvim-lua/plenary.nvim")
  use("nvim-lua/popup.nvim")
  use("nvim-telescope/telescope.nvim")

  use({
    'nvim-lualine/lualine.nvim',
    requires = { 'kyazdani42/nvim-web-devicons', opt = true }
  })

  -- Colorscheme section
  use({
    'catppuccin/nvim',
    as = 'catppuccin'
  })

<<<<<<< Updated upstream
  use {
      'goolord/alpha-nvim',
      -- config = function ()
      --     require'alpha'.setup(require'alpha.themes.dashboard'.config)
      -- end
  }

=======
>>>>>>> Stashed changes
  -- Treesitter
  use("nvim-treesitter/nvim-treesitter", {
    run = ":TSUpdate"
  })

  -- nvim tree
  use({
    'nvim-tree/nvim-tree.lua',
    requires = {
      'nvim-tree/nvim-web-devicons', -- optional, for file icons
    },
    tag = 'nightly' -- optional, updated every week. (see issue #1193)
  })

use {
  'VonHeikemen/lsp-zero.nvim',
  branch = 'v3.x',
  requires = {
    {'williamboman/mason.nvim'},
    {'williamboman/mason-lspconfig.nvim'},

    -- LSP Support
    {'neovim/nvim-lspconfig'},
    -- Autocompletion
    {'hrsh7th/nvim-cmp'},
    {'hrsh7th/cmp-nvim-lsp'},
    {'L3MON4D3/LuaSnip'},
    {'hrsh7th/cmp-nvim-lsp-signature-help'},
  }
}

  -- Mason recommended linter
  use 'mfussenegger/nvim-lint'

  -- Mason recommended formatter
  use 'mhartington/formatter.nvim'

  -- Autoclose
  use 'm4xshen/autoclose.nvim'

  -- Comment
  use {
      'numToStr/Comment.nvim',
      config = function()
          require('Comment').setup()
      end
  }
  -- Text wrapping
  use({
    "andrewferrier/wrapping.nvim",
    config = function()
      require("wrapping").setup({ create_keymaps = false })
    end,
  })

  use { 'alexghergh/nvim-tmux-navigation', config = function()
          require'nvim-tmux-navigation'.setup {
              disable_when_zoomed = true, -- defaults to false
              keybindings = {
                  left = "<C-h>",
                  down = "<C-j>",
                  up = "<C-k>",
                  right = "<C-l>",
                  last_active = "<C-Backspace>",
                  next = "<C-n>",
              }
          }
      end
  }

  -- DAP
  use({
    "rcarriga/nvim-dap-ui",
    requires = { "mfussenegger/nvim-dap" }
  })
  use("jayp0521/mason-nvim-dap.nvim")
  use("nvim-telescope/telescope-dap.nvim")


end)
