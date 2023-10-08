-- import lualine plugin safely
local status, lualine = pcall(require, "lualine")
if not status then
  return
end

-- configure lualine with modified theme
lualine.setup({
  options = {
    theme = "catppuccin",
  },
  disabled_filetypes = { 'packer', 'NVimTree' }
})
