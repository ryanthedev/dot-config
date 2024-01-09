return {
  'goolord/alpha-nvim',
  dependencies = { 'nvim-tree/nvim-web-devicons' },
  priority = 1001,
  config = function()
    local alpha = require('alpha')
    local dashboard = require('alpha.themes.dashboard')

    -- dashboard.section.header.val = {
    --   ".______     ____    ____  ___      .__   __. .___________. __    __   _______  _______   ___________    ____ ",
    --   "|   _  \\    \\   \\  /   / /   \\     |  \\ |  | |           ||  |  |  | |   ____||       \\ |   ____\\   \\  /   / ",
    --   "|  |_)  |    \\   \\/   / /  ^  \\    |   \\|  | `---|  |----`|  |__|  | |  |__   |  .--.  ||  |__   \\   \\/   /  ",
    --   "|      /      \\_    _/ /  /_\\  \\   |  . `  |     |  |     |   __   | |   __|  |  |  |  ||   __|   \\      /   ",
    --   "|  |\\  \\----.   |  |  /  _____  \\  |  |\\   |     |  |     |  |  |  | |  |____ |  '--'  ||  |____   \\    /    ",
    --   "| _| `._____|   |__| /__/     \\__\\ |__| \\__|     |__|     |__|  |__| |_______||_______/ |_______|   \\__/     ",
    -- }

    dashboard.section.header.val = {
      "It is the power of the mind to be unconquerable..."
    }

    alpha.setup(dashboard.opts)
  end
}
