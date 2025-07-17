local function load_env(path)
  local env = {}
  if vim.fn.filereadable(path) ~= 1 then
    return env
  end
  local lines = vim.fn.readfile(path)
  for _, line in ipairs(lines) do
    local trimmed = line:match("^%s*(.-)%s*$")
    if trimmed ~= "" and not trimmed:match("^#") then
      local key, value = trimmed:match("^([^=]+)=(.*)$")
      if key then
        key = key:match("^%s*(.-)%s*$")
        value = value:match("^%s*(.-)%s*$")
        env[key] = value
      end
    end
  end
  return env
end

return {
  {
    "olimorris/codecompanion.nvim",
    dependencies = {
      "nvim-lua/plenary.nvim",
      "nvim-treesitter/nvim-treesitter",
    },
    opts = {
      adapters = {
        dynamic = function()
          local env = load_env(vim.fn.expand("~") .. "/.config/nvim/.env")
          local base_adapter = env.ADAPTER
          local model = env.MODEL
          return require("codecompanion.adapters").extend(base_adapter, {
            schema = {
              model = {
                default = model,
              },
            },
          })
        end,
      },
      strategies = {
        chat = {
          adapter = "dynamic",
        },
        inline = {
          adapter = "dynamic",
        },
        cmd = {
          adapter = "dynamic",
        }
      }
    }
  },
  {
    "github/copilot.vim",
    lazy = false,
  },
  {
    "echasnovski/mini.diff",
    config = function()
      local diff = require("mini.diff")
      diff.setup({
        -- Disabled by default
        source = diff.gen_source.none(),
      })
    end,
  },
  {
    "HakonHarnes/img-clip.nvim",
    opts = {
      filetypes = {
        codecompanion = {
          prompt_for_file_name = false,
          template = "[Image]($FILE_PATH)",
          use_absolute_path = true,
        },
      },
    },
  },
}
