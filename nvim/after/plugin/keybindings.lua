local Remap = require("rtd.keymap")
local nnoremap = Remap.nnoremap
local vnoremap = Remap.vnoremap
local inoremap = Remap.inoremap
local xnoremap = Remap.xnoremap
local nmap = Remap.nmap

---------------------
-- General Keymaps
---------------------
-- clear search highlights
nnoremap("<leader>nh", ":nohl<CR>")

-- delete single character without copying into register
nnoremap("x", '"_x')

-- increment/decrement numbers
nnoremap("<leader>=", "<C-a>") -- increment
nnoremap("<leader>-", "<C-x>") -- decrement

-- window management
-- splits
nnoremap("<leader>sv", "<C-w>v") -- split window vertically
nnoremap("<leader>ss", "<C-w>s") -- split window horizontally
nnoremap("<leader>se", "<C-w>=") -- make split windows equal width & height
nnoremap("<leader>sx", ":close<CR>") -- close current split window
nnoremap("<leader>sh", "<C-w>h") -- move split window focus left
nnoremap("<leader>sl", "<C-w>l") -- move split window focus right
nnoremap("<leader>sj", "<C-w>j") -- move split window focus down
nnoremap("<leader>sk", "<C-w>k") -- move split window focus up
nnoremap("<leader>s>", "<C-w>>") -- increase split width
nnoremap("<leader>s<", "<C-w><") -- decrease split width 
-- tabs
nnoremap("<leader>tn", ":tabnew<CR>") -- open new tab
nnoremap("<leader>tx", ":tabclose<CR>") -- close current tab
nnoremap("<leader>tk", ":tabn<CR>") --  go to next tab
nnoremap("<leader>tj", ":tabp<CR>") --  go to previous tab

-- randy
vnoremap("J", ":m '>+1<CR>gv=gv") --  move current line up 
vnoremap("K", ":m '<-2<CR>gv=gv") --  move current line down 

xnoremap("p", "P") -- Allows to repeat paste 

-- go into things and center screen
nnoremap("gi", "gi<cr>zz");
nnoremap("go", "go<cr>zz");
nnoremap("gd", "gd<cr>zz");
nnoremap("<C-o>", "<C-o><cr>zz");

nnoremap("n", "nzz");
nnoremap("N", "Nzz");
nnoremap("Y", "^y$");
-- page down & up but keep cursor in middle
nnoremap("<C-d>", "<C-d><cr>zz")
nnoremap("<C-u>", "<C-u><cr>zz")

----------------------
-- Plugin Keybinds
----------------------

-- nvim-tree
-- nnoremap("<leader>e", ":NvimTreeToggle<cr>") -- toggle file explorer
-- oil
nnoremap("<leader>e", ":lua require('oil').toggle_float()<cr>") -- toggle file explorer

-- telescope
nnoremap("<leader>ff", "<cmd>Telescope find_files show_untracked=true<cr>") -- find files within current working directory, respects .gitignore
nnoremap("<leader>fs", "<cmd>Telescope live_grep<cr>") -- find string in current working directory as you type
nnoremap("<leader>fc", "<cmd>Telescope grep_string<cr>") -- find string under cursor in current working directory
nnoremap("<leader>fb", "<cmd>Telescope buffers<cr>") -- list open buffers in current neovim instance
nnoremap("<leader>fh", "<cmd>Telescope help_tags<cr>") -- list available help tags
nnoremap("<leader>fcb", "<cmd>Telescope current_buffer_fuzzy_find fuzzy=false case_mode=ignore_case<cr>") -- list available help tags
nnoremap("<leader>fj", "<cmd>Telescope jumplist<cr>") -- search jumplist!!! 
nnoremap("<leader>ft", "<cmd>Telescope colorscheme<cr>")
-- telescope git commands (not on youtube nvim video)
nnoremap("<leader>fgc", "<cmd>Telescope git_commits<cr>") -- list all git commits (use <cr> to checkout) ["gc" for git commits]
nnoremap("<leader>fgb", "<cmd>Telescope git_branches<cr>") -- list git branches (use <cr> to checkout) ["gb" for git branch]
nnoremap("<leader>fgs", "<cmd>Telescope git_status<cr>") -- list current changes per file with diff preview ["gs" for git status]

-- restart lsp server (not on youtube nvim video)
nnoremap("<leader>rs", ":LspRestart<CR>") -- mapping to restart lsp if necessary


-- preview files (netrw)
nnoremap("<leader>pv", "<cmd>Ex<CR>")

