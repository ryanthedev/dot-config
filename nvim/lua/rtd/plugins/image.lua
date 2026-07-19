-- Inline image rendering in markdown (and other filetypes) via the Kitty
-- graphics protocol. Requires a Kitty-graphics-capable terminal (Ghostty ✓)
-- and ImageMagick (`magick`). Pairs with render-markdown.nvim, which styles
-- the text while snacks draws the actual images.
--
-- NOTE: images only display in a *bare* terminal. Inside a herdr pane they
-- will not render (herdr's crossterm UI layer does not pass Kitty graphics).
return {
  'folke/snacks.nvim',
  priority = 1000,
  lazy = false,
  opts = {
    image = {
      enabled = true,
      doc = {
        -- snacks' default only conceals math, so mermaid ("chart") is drawn
        -- *below* its multi-line ```mermaid block — a placement path that
        -- doesn't paint here (math + plain images, which use the inline-replace
        -- or single-line-anchor paths, render fine). Concealing charts too puts
        -- mermaid on the same inline-replace path math uses, so the diagram
        -- replaces the source block inline.
        conceal = function(lang, type)
          return type == "math" or type == "chart"
        end,
      },
    },
  },
}
