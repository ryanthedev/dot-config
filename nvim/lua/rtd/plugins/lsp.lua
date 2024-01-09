require'fidget'.setup{}

local lsp_zero = require('lsp-zero')
local on_attach = function(client, bufnr)
  local opts = {buffer = bufnr, remap = false}

  vim.keymap.set("n", "go", function() vim.lsp.buf.type_definition() end, opts)
  vim.keymap.set("n", "gr", function() vim.lsp.buf.references() end, opts)
  vim.keymap.set("n", "gi", function() vim.lsp.buf.implementation() end, opts)
  vim.keymap.set("n", "gd", function() vim.lsp.buf.definition() end, opts)
  vim.keymap.set("n", "gl", function() vim.diagnostic.open_float() end, opts)
  vim.keymap.set("n", "K", function() vim.lsp.buf.hover() end, opts)
  vim.keymap.set("n", "<leader>vws", function() vim.lsp.buf.workspace_symbol() end, opts)
  vim.keymap.set("n", "[d", function() vim.diagnostic.goto_next() end, opts)
  vim.keymap.set("n", "]d", function() vim.diagnostic.goto_prev() end, opts)
  vim.keymap.set("n", "<leader>vca", function() vim.lsp.buf.code_action() end, opts)
  vim.keymap.set("n", "<leader>vrn", function() vim.lsp.buf.rename() end, opts)
  vim.keymap.set("i", "<C-i>", function() vim.lsp.buf.signature_help() end, opts)
end

-- nvim-cmp supports additional completion capabilities, so broadcast that to servers
local capabilities = vim.lsp.protocol.make_client_capabilities()
capabilities = require('cmp_nvim_lsp').default_capabilities(capabilities)

lsp_zero.on_attach(on_attach)

-- local lsp_configurations = require('lspconfig.configs')
--
-- if not lsp_configurations.roslyn then
--   lsp_configurations.roslyn  = {
--     default_config = {
--       name = 'roslyn ',
--       cmd = {'roslyn'},
--       filetypes = {'cs'},
--       root_dir = require('lspconfig.util').root_pattern('.sln')
--     }
--   }
-- end

require("roslyn").setup({
    on_attach =  on_attach,
    capabilities = capabilities
})

require('mason').setup({})
require('mason-lspconfig').setup({
  ensure_installed = {'tsserver'},
  handlers = {
    lsp_zero.default_setup,
    lua_ls = function()
      local lua_opts = lsp_zero.nvim_lua_ls()
      require('lspconfig').lua_ls.setup(lua_opts)
    end
  }
})

local cmp = require('cmp')
local cmp_select = {behavior = cmp.SelectBehavior.Select}

cmp.setup({
  sources = {
    {name = 'path'},
    {name = 'nvim_lsp'},
    {name = 'nvim_lua'},
    {name = 'buffer'},
    {name = 'nvim_lsp_signature_help'},
  },
  formatting = lsp_zero.cmp_format(),
  mapping = cmp.mapping.preset.insert({
    ['<C-b>'] = cmp.mapping.scroll_docs(-4),
    ['<C-f>'] = cmp.mapping.scroll_docs(4),
    ['<C-o>'] = cmp.mapping.complete(),
    ['<C-e>'] = cmp.mapping.abort(),
    ['<CR>'] = cmp.mapping.confirm({ select = true }),
  }),
  preselect = 'item',
  completion = {
    completeopt = 'menu,menuone,noinsert'
  },
})
