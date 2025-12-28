-- Text transformations: JSON, URL, HTML, Base64
-- Works on visual selection or entire buffer

local M = {}

-- Transformation definitions: { name, command, description }
M.transformations = {
  -- JSON
  { key = "mjp", name = "JSON Prettify", cmd = "jq .", desc = "Format JSON with indentation" },
  { key = "mjm", name = "JSON Minify", cmd = "jq -c .", desc = "Compact JSON to single line" },
  { key = "mje", name = "JSON Escape", cmd = "jq -Rs .", desc = "Escape string as JSON" },
  { key = "mju", name = "JSON Unescape", cmd = "jq -r .", desc = "Unescape JSON string" },
  -- URL
  { key = "mue", name = "URL Encode", cmd = [[python3 -c "import sys,urllib.parse;print(urllib.parse.quote(sys.stdin.read().strip()),end='')"]], desc = "Percent-encode URL" },
  { key = "mud", name = "URL Decode", cmd = [[python3 -c "import sys,urllib.parse;print(urllib.parse.unquote(sys.stdin.read().strip()),end='')"]], desc = "Decode percent-encoded URL" },
  -- HTML
  { key = "mhe", name = "HTML Escape", cmd = [[python3 -c "import sys,html;print(html.escape(sys.stdin.read()),end='')"]], desc = "Escape HTML entities" },
  { key = "mhu", name = "HTML Unescape", cmd = [[python3 -c "import sys,html;print(html.unescape(sys.stdin.read()),end='')"]], desc = "Unescape HTML entities" },
  -- Base64
  { key = "mbe", name = "Base64 Encode", cmd = "base64", desc = "Encode to Base64" },
  { key = "mbd", name = "Base64 Decode", cmd = "base64 -d", desc = "Decode from Base64" },
}

-- Get text from visual selection or entire buffer
local function get_text(mode)
  if mode == "v" or mode == "V" or mode == "\22" then
    -- Visual mode: get selection using marks
    local start_pos = vim.fn.getpos("'<")
    local end_pos = vim.fn.getpos("'>")
    local start_row, start_col = start_pos[2] - 1, start_pos[3] - 1
    local end_row, end_col = end_pos[2] - 1, end_pos[3]

    -- Clamp end_col to actual line length
    local end_line = vim.api.nvim_buf_get_lines(0, end_row, end_row + 1, false)[1] or ""
    end_col = math.min(end_col, #end_line)

    local lines = vim.api.nvim_buf_get_text(0, start_row, start_col, end_row, end_col, {})
    return table.concat(lines, "\n"), { start_row, start_col }, { end_row, end_col }
  else
    -- Normal mode: entire buffer
    local lines = vim.api.nvim_buf_get_lines(0, 0, -1, false)
    return table.concat(lines, "\n"), nil, nil
  end
end

-- Replace text in visual selection or entire buffer
local function set_text(new_text, start_pos, end_pos)
  local lines = vim.split(new_text, "\n", { trimempty = false })
  -- Remove trailing empty line if present (from shell output)
  if #lines > 1 and lines[#lines] == "" then
    table.remove(lines)
  end

  if start_pos and end_pos then
    -- Visual mode: replace selection (positions already 0-indexed)
    vim.api.nvim_buf_set_text(0, start_pos[1], start_pos[2], end_pos[1], end_pos[2], lines)
  else
    -- Normal mode: replace entire buffer
    vim.api.nvim_buf_set_lines(0, 0, -1, false, lines)
  end
end

-- Run transformation
function M.transform(cmd, mode)
  local text, start_pos, end_pos = get_text(mode)
  if not text or text == "" then
    vim.notify("No text to transform", vim.log.levels.WARN)
    return
  end

  local result = vim.fn.system(cmd, text)
  if vim.v.shell_error ~= 0 then
    vim.notify("Transform failed: " .. result, vim.log.levels.ERROR)
    return
  end

  set_text(result, start_pos, end_pos)
end

-- Create transform function for a specific command
local function make_transform_fn(cmd)
  return function()
    local mode = vim.fn.mode()
    M.transform(cmd, mode)
  end
end

-- Telescope picker for transformations
local function telescope_transform(mode)
  mode = mode or "n"
  local ok, _ = pcall(require, "telescope.builtin")
  if not ok then
    vim.notify("Telescope not available", vim.log.levels.ERROR)
    return
  end

  local pickers = require("telescope.pickers")
  local finders = require("telescope.finders")
  local conf = require("telescope.config").values
  local actions = require("telescope.actions")
  local action_state = require("telescope.actions.state")

  local items = {}
  for _, t in ipairs(M.transformations) do
    table.insert(items, {
      display = string.format("[%s] %s - %s", t.key, t.name, t.desc),
      name = t.name,
      cmd = t.cmd,
    })
  end

  pickers.new({}, {
    prompt_title = "Transform",
    finder = finders.new_table({
      results = items,
      entry_maker = function(entry)
        return {
          value = entry,
          display = entry.display,
          ordinal = entry.name .. " " .. entry.display,
        }
      end,
    }),
    sorter = conf.generic_sorter({}),
    attach_mappings = function(prompt_bufnr, map)
      actions.select_default:replace(function()
        actions.close(prompt_bufnr)
        local selection = action_state.get_selected_entry()
        if selection then
          M.transform(selection.value.cmd, mode)
        end
      end)
      return true
    end,
  }):find()
end

return {
  "nvim-lua/plenary.nvim", -- dependency for telescope
  config = function()
    -- Set up keybindings
    for _, t in ipairs(M.transformations) do
      local fn = make_transform_fn(t.cmd)
      -- Normal mode: transform entire buffer
      vim.keymap.set("n", "<leader>" .. t.key, fn, { desc = t.name })
      -- Visual mode: transform selection
      vim.keymap.set("v", "<leader>" .. t.key, function()
        -- Exit visual mode first to set '< and '> marks
        local esc = vim.api.nvim_replace_termcodes("<Esc>", true, false, true)
        vim.api.nvim_feedkeys(esc, "x", false)
        vim.schedule(function()
          M.transform(t.cmd, "v")
        end)
      end, { desc = t.name .. " (selection)" })
    end

    -- Command and keybinding to open picker
    vim.api.nvim_create_user_command("Transform", function() telescope_transform("n") end, { desc = "Open transform picker" })
    vim.keymap.set("n", "<leader>mm", function() telescope_transform("n") end, { desc = "Transform picker" })
    vim.keymap.set("v", "<leader>mm", function()
      -- Exit visual mode to set marks, then open picker
      local esc = vim.api.nvim_replace_termcodes("<Esc>", true, false, true)
      vim.api.nvim_feedkeys(esc, "x", false)
      vim.schedule(function()
        telescope_transform("v")
      end)
    end, { desc = "Transform picker (selection)" })
  end,
}
