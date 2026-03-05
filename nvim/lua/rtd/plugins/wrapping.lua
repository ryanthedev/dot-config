return {
	"andrewferrier/wrapping.nvim",
	event = "BufReadPost",
	config = function()
		require("wrapping").setup()
	end,
}
