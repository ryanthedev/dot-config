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
  sections = {
    lualine_c = {
      {
        'filename',
        path = 4
      }
    }
  },
  disabled_filetypes = { 'packer', 'NvimTree_1' }
})
