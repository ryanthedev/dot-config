return {
  'mfussenegger/nvim-lint',
  event = { "BufReadPre", "BufNewFile" },
  config = function()
    local lint = require('lint')

    -- Configure linters by filetype (only if installed)
    lint.linters_by_ft = {
      javascript = { "eslint_d" },
      typescript = { "eslint_d" },
      javascriptreact = { "eslint_d" },
      typescriptreact = { "eslint_d" },
      python = { "ruff" },
      go = { "golangcilint" },
      bash = { "shellcheck" },
      sh = { "shellcheck" },
    }

    -- Lint on save and when leaving insert mode
    vim.api.nvim_create_autocmd({ "BufWritePost", "InsertLeave" }, {
      callback = function()
        -- Only lint if there's a linter configured for this filetype
        if lint.linters_by_ft[vim.bo.filetype] then
          lint.try_lint()
        end
      end,
    })
  end
}
