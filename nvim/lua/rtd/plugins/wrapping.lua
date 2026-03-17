return {
	"andrewferrier/wrapping.nvim",
	event = "BufReadPost",
	config = function()
		require("wrapping").setup({
			soft_wrap_filetypes = { "markdown", "latex", "tex" },
		})
	end,
}
