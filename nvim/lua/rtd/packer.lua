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
  use("glepnir/zephyr-nvim")
  use("rockerBOO/boo-colorscheme-nvim")
  use("sainnhe/edge")
  use("marko-cerovac/material.nvim")
  use("Th3Whit3Wolf/space-nvim")
  use("ray-x/starry.nvim")
  use("shaunsingh/nord.nvim")
  use("NTBBloodbath/doom-one.nvim")
  use("FrenzyExists/aquarium-vim")
  use("EdenEast/nightfox.nvim")
  use("Everblush/nvim")
  use("adisen99/apprentice.nvim")
  use("rmehri01/onenord.nvim")


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

  -- LSP Setup UI
  use("j-hui/fidget.nvim")
  
  -- Autocomplete engine
  use("hrsh7th/nvim-cmp")

  -- null-ls magic
  use("jose-elias-alvarez/null-ls.nvim")
  -- Completion source
--  use("hrsh7th/cmp-buffer")
 -- use("saadparwaiz1/cmp_luasnip")
  use("hrsh7th/cmp-nvim-lsp")

  -- Snippet engine
 -- use("L3MON4D3/LuaSnip")
  -- Snippet colletion
 -- use("rafamadriz/friendly-snippets")


  -- Dashboard
 -- use("glepnir/dashboard-nvim")

  use("andrewferrier/wrapping.nvim")
  -- DAP
  use({
    "rcarriga/nvim-dap-ui",
    requires = { "mfussenegger/nvim-dap" }
  })
  use("jayp0521/mason-nvim-dap.nvim")
  use("nvim-telescope/telescope-dap.nvim")

  -- Formatter
  use("mhartington/formatter.nvim")



  -- Terminal Toggle
  use({
    "akinsho/toggleterm.nvim",
    tag = '*',
    config = function()
      require("toggleterm").setup()
    end
  })


  -- Test Runners
  use({
    "nvim-neotest/neotest",
    requires = {
      "Issafalcon/neotest-dotnet",
      "antoinemadec/FixCursorHold.nvim"
    }
  })
end)
