return {
	"andrewferrier/wrapping.nvim",
	event = "BufReadPost",
	config = function()
		local wrapping = require("wrapping")
		wrapping.setup({}) -- default heuristic + allowlist (already includes markdown/tex/latex)

		-- Always soft-wrap these prose filetypes, overriding the length heuristic
		-- (which flip-flops to hard on markdown mixing long prose with short lines
		-- like headings and tables). This is what the old, ignored
		-- `soft_wrap_filetypes` option was meant to do. Uses the plugin API so its
		-- wrapmode state and statusline stay consistent. Deferred with schedule so
		-- it runs *after* wrapping.nvim's own BufReadPost heuristic.
		local prose = { markdown = true, tex = true, latex = true }
		local function force_soft()
			if prose[vim.bo.filetype] and vim.b.wrapmode ~= "soft" then
				wrapping.soft_wrap_mode()
			end
		end
		vim.api.nvim_create_autocmd("FileType", {
			pattern = { "markdown", "tex", "latex" },
			callback = function()
				vim.schedule(force_soft)
			end,
		})
		-- Handle the buffer that triggered this lazy-load (its FileType may have
		-- fired before the autocmd above existed).
		vim.schedule(force_soft)
	end,
}
