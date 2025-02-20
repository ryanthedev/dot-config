local vim = vim
local api = vim.api
local M = {}
-- function to create a list of commands and convert them to autocommands
-------- This function is taken from https://github.com/norcalli/nvim_utils
function M.nvim_create_augroups(definitions)
	for group_name, definition in pairs(definitions) do
		api.nvim_command("augroup " .. group_name)
		api.nvim_command("autocmd!")
		for _, def in ipairs(definition) do
			local command = table.concat(vim.tbl_flatten({ "autocmd", def }), " ")
			api.nvim_command(command)
		end
		api.nvim_command("augroup END")
	end
end

-- Example
-- :Redir lua =vim.lsp.get_clients()[1].server_capabilities
-- vim.api.nvim_create_user_command('Redir', function(ctx)
--   local lines = vim.split(vim.api.nvim_exec(ctx.args, true), '\n', { plain = true })
--   vim.cmd('new')
--   vim.api.nvim_buf_set_lines(0, 0, -1, false, lines)
--   vim.opt_local.modified = false
-- end, { nargs = '+', complete = 'command' })


local autoCommands = {
	-- other autocommands
	-- open_folds = {
	-- 	{ "BufReadPost,FileReadPost", "*", "normal zR" },
	-- },
  -- xml_folds = {
  --   { "FileType", "xml", "let g:xml_syntax_folding=1" },
  --   { "FileType", "xml", "setlocal foldmethod=syntax" },
  --   { "FileType", "xml", ":syntax on" },
  --   { "FileType", "xml", "normal zR" },
  -- }
}

-- M.nvim_create_augroups(autoCommands)
--
--
vim.api.nvim_create_autocmd("FileType",  {
      pattern = { "json" },
      callback = function()
        vim.api.nvim_set_option_value("formatprg", "jq", { scope = 'local' })
      end,
})

vim.api.nvim_create_autocmd('LspAttach', {
  callback = function(args)
    local client = vim.lsp.get_client_by_id(args.data.client_id)

    if client:supports_method('textDocument/inlayHint') then
      vim.lsp.inlay_hint.enable(true, {bufnr = args.buf})
    end
  end,
})

vim.api.nvim_create_autocmd('LspAttach', {
  callback = function(args)
    local client = vim.lsp.get_client_by_id(args.data.client_id)

    -- if client:supports_method('textDocument/documentHighlight') then
    --   vim.notify('client supports document highlight')
    --   local autocmd = vim.api.nvim_create_autocmd
    --   local augroup = vim.api.nvim_create_augroup('lsp_highlight', {clear = false})
    --
    --   vim.api.nvim_clear_autocmds({buffer = bufnr, group = augroup})
    --
    --   autocmd({'CursorHold'}, {
    --     group = augroup,
    --     buffer = args.buf,
    --     callback = vim.lsp.buf.document_highlight,
    --   })
    --
    --   autocmd({'CursorMoved'}, {
    --     group = augroup,
    --     buffer = args.buf,
    --     callback = vim.lsp.buf.clear_references,
    --   })
    -- end
  end,
})
