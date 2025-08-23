return {
  text = "BerkeleyMono Nerd Font", -- Used for text
  numbers = "BerkeleyMono Nerd Font", -- Used for numbers

  -- Unified font style map
  -- Berkeley Mono only has: Regular, Bold, Oblique, Bold Oblique
  style_map = {
    ["Regular"] = "Regular",
    ["Semibold"] = "Bold",      -- Map to Bold since Semibold doesn't exist
    ["Bold"] = "Bold",
    ["Heavy"] = "Bold",         -- Map to Bold since Heavy doesn't exist
    ["Black"] = "Bold",         -- Map to Bold since Black doesn't exist
  }
}
