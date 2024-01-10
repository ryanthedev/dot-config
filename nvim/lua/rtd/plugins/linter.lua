return {
  'mfussenegger/nvim-lint',
  config = function()
    local lint = require('lint')
    lint.inters_by_ft = {
      lua = {
      }
    }


    vim.api.nvim_create_autocmd({ "BufWritePost" }, {
      callback = function()
        lint.try_lint()
      end,
    })
  end
}
