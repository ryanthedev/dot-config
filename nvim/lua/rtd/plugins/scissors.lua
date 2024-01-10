return {
	"chrisgrieser/nvim-scissors",
	dependencies = "nvim-telescope/telescope.nvim", -- optional
  config = function()
    require('scissors').setup({
      snippetDir = "~/.config/snippets",
    })
    vim.keymap.set("n", "<leader>se", function() require("scissors").editSnippet() end)
    -- When used in visual mode prefills the selection as body.
    vim.keymap.set({ "n", "x" }, "<leader>sa", function() require("scissors").addNewSnippet() end)
  end
}
