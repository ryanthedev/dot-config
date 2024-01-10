return {
  'zootedb0t/citruszest.nvim',
  lazy = false,
  priority = 1000,
  config = function()
    require("citruszest").setup({})
    vim.cmd('colorscheme citruszest')
  end,
}
