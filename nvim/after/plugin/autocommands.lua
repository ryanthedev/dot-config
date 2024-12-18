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
