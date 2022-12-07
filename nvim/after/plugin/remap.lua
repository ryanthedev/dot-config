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
