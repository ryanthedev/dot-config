return {
  "kevinhwang91/nvim-ufo",
  dependencies = {
    {'kevinhwang91/promise-async'},
    -- {'nvim-treesitter/nvim-treesitter'},
  },
  config = function()
    local ufo = require('ufo')
    ufo.setup()
    -- ufo.setup({
    --   provider_selector = function (bufnr, filetype, buftype)
    --     return {'treesitter', 'indent'}
    --   end
    -- })

    vim.keymap.set('n', 'zR', ufo.openAllFolds)
    vim.keymap.set('n', 'zM', ufo.closeAllFolds)
  end
}
