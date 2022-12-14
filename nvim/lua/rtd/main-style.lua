local status, _ = pcall(vim.cmd, "colorscheme oceanic")
if not status then
  print("Colorscheme not found!") -- print error if colorscheme not installed
  return
end


