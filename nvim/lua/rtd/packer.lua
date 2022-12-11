return require("packer").startup(function(use)
  use("wbthomason/packer.nvim")

  -- TJ created lodash of neovim
  use("nvim-lua/plenary.nvim")
  use("nvim-lua/popup.nvim")
  use("nvim-telescope/telescope.nvim")

  use({
      'nvim-lualine/lualine.nvim',
      requires = { 'kyazdani42/nvim-web-devicons', opt = true }
  })

    -- Colorscheme section
  use("gruvbox-community/gruvbox")
  use("folke/tokyonight.nvim")

  use("nvim-treesitter/nvim-treesitter", {
      run = ":TSUpdate"
  })
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

  -- Autocomplete engine
  use("hrsh7th/nvim-cmp")

  -- Completion source
  use("hrsh7th/cmp-buffer")
  use("saadparwaiz1/cmp_luasnip")
  use("hrsh7th/cmp-nvim-lsp")

  -- Snippet engine
  use("L3MON4D3/LuaSnip")
  -- Snippet colletion 
  use("rafamadriz/friendly-snippets")


  -- Dashboard
  use("glepnir/dashboard-nvim")

  -- DAP
  use({
    "rcarriga/nvim-dap-ui",
    requires = { "mfussenegger/nvim-dap"}
  })
  use("jayp0521/mason-nvim-dap.nvim")
  use("nvim-telescope/telescope-dap.nvim")



  -- Terminal Toggle
  use({
    "akinsho/toggleterm.nvim",
    tag = '*',
    config = function()
      require("toggleterm").setup()
    end
  })

end)
