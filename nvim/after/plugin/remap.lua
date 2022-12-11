local Remap = require("rtd.keymap")
local nnoremap = Remap.nnoremap
local vnoremap = Remap.vnoremap
local inoremap = Remap.inoremap
local xnoremap = Remap.xnoremap
local nmap = Remap.nmap


---------------------
-- General Keymaps
---------------------
-- use jk to exit insert mode
inoremap("jk", "<ESC>")

-- clear search highlights
nnoremap("<leader>nh", ":nohl<CR>")

-- delete single character without copying into register
nnoremap("x", '"_x')

-- increment/decrement numbers
nnoremap("<leader>+", "<C-a>") -- increment
nnoremap("<leader>-", "<C-x>") -- decrement

-- window management
nnoremap("<leader>sv", "<C-w>v") -- split window vertically
nnoremap("<leader>sh", "<C-w>s") -- split window horizontally
nnoremap("<leader>se", "<C-w>=") -- make split windows equal width & height
nnoremap("<leader>sx", ":close<CR>") -- close current split window

nnoremap("<leader>to", ":tabnew<CR>") -- open new tab
nnoremap("<leader>tx", ":tabclose<CR>") -- close current tab
nnoremap("<leader>tn", ":tabn<CR>") --  go to next tab
nnoremap("<leader>tp", ":tabp<CR>") --  go to previous tab

----------------------
-- Plugin Keybinds
----------------------

-- vim-maximizer
nnoremap("<leader>sm", ":MaximizerToggle<CR>") -- toggle split window maximization

-- nvim-tree
nnoremap("<leader>e", ":NvimTreeToggle<CR>") -- toggle file explorer

-- telescope
nnoremap("<leader>ff", "<cmd>Telescope find_files<cr>") -- find files within current working directory, respects .gitignore
nnoremap("<leader>fs", "<cmd>Telescope live_grep<cr>") -- find string in current working directory as you type
nnoremap("<leader>fc", "<cmd>Telescope grep_string<cr>") -- find string under cursor in current working directory
nnoremap("<leader>fb", "<cmd>Telescope buffers<cr>") -- list open buffers in current neovim instance
nnoremap("<leader>fh", "<cmd>Telescope help_tags<cr>") -- list available help tags
nnoremap("<leader>fg", "<cmd>Telescope current_buffer_fuzzy_find fuzzy=false case_mode=ignore_case<cr>") -- list available help tags

-- telescope git commands (not on youtube nvim video)
nnoremap("<leader>gc", "<cmd>Telescope git_commits<cr>") -- list all git commits (use <cr> to checkout) ["gc" for git commits]
nnoremap("<leader>gfc", "<cmd>Telescope git_bcommits<cr>") -- list git commits for current file/buffer (use <cr> to checkout) ["gfc" for git file commits]
nnoremap("<leader>gb", "<cmd>Telescope git_branches<cr>") -- list git branches (use <cr> to checkout) ["gb" for git branch]
nnoremap("<leader>gs", "<cmd>Telescope git_status<cr>") -- list current changes per file with diff preview ["gs" for git status]

-- restart lsp server (not on youtube nvim video)
nnoremap("<leader>rs", ":LspRestart<CR>") -- mapping to restart lsp if necessary

-- page down & up but keep cursor in middle
nnoremap("<C-d>", "<C-d>zz")
nnoremap("<C-u>", "<C-u>zz")

-- preview files (netrw)
nnoremap("<leader>pv", "<cmd>Ex<CR>")



-- Terminal Toggle
nnoremap("<leader>nth", "<cmd>ToggleTerm size=18 direction=horizontal<CR>")

nnoremap("<F4>", ":lua require('dapui').toggle()<CR>")
nnoremap("<F7>", ":lua require('dap').toggle_breakpoint()<CR>")
nnoremap("<F5>", ":lua require('dap').continue()<CR>")

nnoremap("<F1>", ":lua require('dap').step_over()<CR>")
nnoremap("<F2>", ":lua require('dap').step_into()<CR>")
nnoremap("<F3>", ":lua require('dap').step_out()<CR>")

nnoremap("<leader>dsc", ":lua require('dap').continue()<CR>")
nnoremap("<leader>dsv", ":lua require('dap').step_over()<CR>")
nnoremap("<leader>dsi", ":lua require('dap').step_into()<CR>")
nnoremap("<leader>dso", ":lua require('dap').step_out()<CR>")

nnoremap("<leader>dhh", ":lua require('dap.ui.variables').hover()<CR>")
vnoremap("<leader>dhv", ":lua require('dap.ui.variables').visual_hover()<CR>")

nnoremap("<leader>duh", ":lua require('dap.ui.widgets').hover()<CR>")
nnoremap("<leader>duf", ":lua local widgets=require('dap.ui.widgets');widgets.centered_float(widgets.scopes)<CR>")

nnoremap("<leader>dro", ":lua require('dap').repl.open()<CR>")
nnoremap("<leader>drl", ":lua require('dap').repl.run_last()<CR>")

nnoremap("<leader>dbc", ":lua require('dap').set_breakpoint(vim.fn.input('Breakpoint condition: '))<CR>")
nnoremap("<leader>dbm", ":lua require('dap').set_breakpoint({ nil, nil, vim.fn.input('Log point message: '))<CR>")
nnoremap("<leader>dbt", ":lua require('dap').toggle_breakpoint()<CR>")

nnoremap("<leader>dc", ":lua require('dap.ui.variables').scopes()<CR>")
nnoremap("<leader>di", ":lua require('dapui').toggle()<CR>")

