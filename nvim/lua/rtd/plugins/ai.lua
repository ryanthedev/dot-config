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
          local selected_adapter = vim.g.codecompanion_adapter or env.ADAPTER or "anthropic"  -- Fallback to anthropic if nothing set
          local upper_adapter = selected_adapter:upper()
          local model = env[upper_adapter .. "_MODEL"] or "default-model"  -- Adapter-specific model
          local api_key = env[upper_adapter .. "_API_KEY"]  -- Adapter-specific API key

          if not api_key then
            error("API key not found in .env for " .. selected_adapter)
          end

          return require("codecompanion.adapters").extend(selected_adapter, {
            env = {
              api_key = api_key,
            },
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
