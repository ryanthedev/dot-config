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

  -- make things transparent
  use("xiyaowong/nvim-transparent")

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

  -- LSP, DAP, goodness
  -- External tool installer
  use("williamboman/mason.nvim")

  -- Lspconfig & mason extension
  use("williamboman/mason-lspconfig.nvim")
  use("neovim/nvim-lspconfig")

  -- Mason recommended linter
  use 'mfussenegger/nvim-lint'

  -- Mason recommended formatter
  use 'mhartington/formatter.nvim'

  -- LSP Steup UI
  use("j-hui/fidget.nvim")

  -- wrod 
  --
  -- pryamid 
  -- wrod
-- Text wrapping
  use({
    "andrewferrier/wrapping.nvim",
    config = function()
      require("wrapping").setup()
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
