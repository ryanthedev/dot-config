local status, nvim_lsp = pcall(require, "lspconfig")
if (not status) then return end

local protocol = require("vim.lsp.protocol")

local on_attach = function(client, bufnr)
  buf_set_option("omnifunc", "v:lua.vim.lsp.omnifunc")

  if client.server_capabilities.documentFormattingProvider then
    vim.api.nvim_create_autocmd("BufWritePre", {
      group = vim.api.nvim_create_augroup("Format", { clear = true }),
      buffer = bufnr,
      callback = function() vim.lsp.buf.formatting_seq_sync() end
    })
  end
end

local capabilities = require("cmp_nvim_lsp").update_capabilities(
  vim.lsp.protocol.make_client_capabilities()
)
nvim_lsp.flow.setup {
  on_attach = on_attach,
  capabilities = capabilities
}

nvim_lsp.sumneko_lua.setup {
 on_attach = on_attach,
 settings = {
   Lua = {
     diagnostics = {
       globals = { "vim" },
     },
     workspace = {
       library = vim.api.nvim_get_runtime_file("", true),
       checkThirdParty = false
     },
   }
 }
}

nvim_lsp.tsserver.setup {
  on_attach = on_attach,
  filetypes = { "typescript", "typescriptreact", "typescript.tsx" },
  cmd = { "typescript-language-server", "--stdio" },
  capabilities = capabilities
}
