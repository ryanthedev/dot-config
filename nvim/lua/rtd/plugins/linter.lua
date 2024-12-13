return {
  'mfussenegger/nvim-lint',
  config = function()
    local lint = require('lint')
    lint.linters_by_ft = {
      lua = {
      }
    }

    vim.api.nvim_create_autocmd({ "BufWritePost" }, {
      callback = function()
        if lint.linters_by_ft[vim.bo.filetype] then
          lint.try_lint()
        end
      end,
    })
  end
}
