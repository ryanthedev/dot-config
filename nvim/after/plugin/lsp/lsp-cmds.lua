local lsp_cmds = vim.api.nvim_create_augroup('lsp_cmds', {clear = true})

local Remap = require("rtd.keymap")
local nnoremap = Remap.nnoremap
local xnoremap = Remap.xnoremap


vim.api.nvim_create_autocmd('LspAttach', {
  group = lsp_cmds,
  desc = 'LSP actions',
  callback = function()
    nnoremap('K', '<cmd>lua vim.lsp.buf.hover()<cr>')
    nnoremap('gd', '<cmd>lua vim.lsp.buf.definition()<cr>')
    nnoremap('gD', '<cmd>lua vim.lsp.buf.declaration()<cr>')
    nnoremap('gi', '<cmd>lua vim.lsp.buf.implementation()<cr>')
    nnoremap('go', '<cmd>lua vim.lsp.buf.type_definition()<cr>')
    nnoremap('gr', '<cmd>lua vim.lsp.buf.references()<cr>')
    nnoremap('<C-k>', '<cmd>lua vim.lsp.buf.signature_help()<cr>')
    nnoremap('crn', '<cmd>lua vim.lsp.buf.rename()<cr>')
    nnoremap('cfd', '<cmd>lua vim.lsp.buf.format({async = true})<cr>')
    nnoremap('cca', '<cmd>lua vim.lsp.buf.code_action()<cr>')
    xnoremap('cca', '<cmd>lua vim.lsp.buf.range_code_action()<cr>')
    nnoremap('gl', '<cmd>lua vim.diagnostic.open_float()<cr>')
    nnoremap('[d', '<cmd>lua vim.diagnostic.goto_prev()<cr>')
    nnoremap(']d', '<cmd>lua vim.diagnostic.goto_next()<cr>')
  end
})
