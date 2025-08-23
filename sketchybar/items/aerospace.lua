local colors = require("colors")
local icons = require("icons")
local settings = require("settings")
local app_icons = require("helpers.app_icons")

local spaces = {}
local space_brackets = {}

-- Helper function to parse aerospace output
local function parse_string_to_table(str)
  local result = {}
  for line in str:gmatch("[^\r\n]+") do
    table.insert(result, line)
  end
  return result
end

-- Function to get unique apps for a workspace
local function get_workspace_apps(workspace)
  local apps_output = io.popen("aerospace list-windows --workspace " .. workspace .. " --format '%{app-name}'"):read("*a")
  local apps = {}
  local app_set = {}
  
  for app in apps_output:gmatch("[^\r\n]+") do
    if not app_set[app] then
      app_set[app] = true
      table.insert(apps, app)
    end
  end
  
  return apps
end

-- Function to generate icon line for apps
local function generate_icon_line(apps)
  if #apps == 0 then
    return " —"
  end
  
  local icon_line = ""
  for _, app in ipairs(apps) do
    local lookup = app_icons[app]
    local icon = lookup or app_icons["Default"] or ":default:"
    icon_line = icon_line .. " " .. icon
  end
  
  return icon_line
end

-- Function to update workspace items
local function update_workspaces()
  -- Remove all existing space items and brackets
  for workspace, space in pairs(spaces) do
    sbar.remove(space)
    spaces[workspace] = nil
  end
  for _, bracket in pairs(space_brackets) do
    sbar.remove(bracket)
  end
  space_brackets = {}
  
  -- Get current aerospace workspaces
  local workspaces = parse_string_to_table(io.popen("aerospace list-workspaces --all"):read("*a"))
  
  -- Get the currently focused workspace
  local focused_workspace = io.popen("aerospace list-workspaces --focused"):read("*a"):gsub("%s+", "")
  
  for i, workspace in ipairs(workspaces) do
    -- Get apps for this workspace
    local apps = get_workspace_apps(workspace)
    local icon_line = generate_icon_line(apps)
    
    local space = sbar.add("item", "space." .. workspace, {
      icon = {
        font = { family = settings.font.numbers },
        string = workspace,
        padding_left = 15,
        padding_right = 8,
        color = colors.white,
        highlight_color = colors.red,
      },
      label = {
        padding_right = 20,
        color = colors.grey,
        highlight_color = colors.white,
        font = "sketchybar-app-font:Regular:16.0",
        y_offset = -1,
        string = icon_line,
      },
      padding_right = 1,
      padding_left = 1,
      background = {
        color = colors.bg1,
        border_width = 1,
        height = 26,
        border_color = colors.black,
      },
      popup = { background = { border_width = 5, border_color = colors.black } }
    })

    spaces[workspace] = space

    -- Single item bracket for space items to achieve double border on highlight
    local space_bracket = sbar.add("bracket", { space.name }, {
      background = {
        color = colors.transparent,
        border_color = colors.bg2,
        height = 28,
        border_width = 2
      }
    })
    
    space_brackets[workspace] = space_bracket

    -- Set initial highlight for focused workspace
    if workspace == focused_workspace then
      space:set({
        icon = { highlight = true },
        label = { highlight = true },
        background = { border_color = colors.black }
      })
      space_bracket:set({
        background = { border_color = colors.grey }
      })
    end

    -- Subscribe to aerospace workspace change events
    space:subscribe("aerospace_workspace_change", function(env)
      local selected = env.FOCUSED_WORKSPACE == workspace
      
      -- Update apps for this workspace
      local current_apps = get_workspace_apps(workspace)
      local current_icon_line = generate_icon_line(current_apps)
      
      space:set({
        icon = { highlight = selected },
        label = { 
          highlight = selected,
          string = current_icon_line
        },
        background = { border_color = selected and colors.black or colors.bg2 }
      })
      space_bracket:set({
        background = { border_color = selected and colors.grey or colors.bg2 }
      })
      
      -- Check if workspaces have changed and update if needed
      local current_workspaces = parse_string_to_table(io.popen("aerospace list-workspaces --all"):read("*a"))
      local workspace_set = {}
      for _, ws in ipairs(current_workspaces) do
        workspace_set[ws] = true
      end
      
      -- Check if any existing space is no longer in the workspace list
      local needs_update = false
      for ws, _ in pairs(spaces) do
        if not workspace_set[ws] then
          needs_update = true
          break
        end
      end
      
      -- Check if any new workspace exists that we don't have
      if not needs_update then
        for _, ws in ipairs(current_workspaces) do
          if not spaces[ws] then
            needs_update = true
            break
          end
        end
      end
      
      if needs_update then
        update_workspaces()
      end
    end)

    -- Handle mouse clicks to switch workspaces
    space:subscribe("mouse.clicked", function(env)
      if env.BUTTON == "left" then
        sbar.exec("aerospace workspace " .. workspace)
      end
    end)
  end
end

-- Subscribe to window focus change to update app icons
local window_observer = sbar.add("item", {
  drawing = false,
  updates = true,
})

window_observer:subscribe("aerospace_workspace_change", function(env)
  -- Update apps for all workspaces
  for workspace, space in pairs(spaces) do
    local apps = get_workspace_apps(workspace)
    local icon_line = generate_icon_line(apps)
    
    sbar.animate("tanh", 10, function()
      space:set({ label = { string = icon_line } })
    end)
  end
end)

-- Initialize workspaces
update_workspaces()

-- Spaces indicator
local spaces_indicator = sbar.add("item", {
  padding_left = -3,
  padding_right = 0,
  icon = {
    padding_left = 8,
    padding_right = 9,
    color = colors.grey,
    string = icons.switch.on,
  },
  label = {
    width = 0,
    padding_left = 0,
    padding_right = 8,
    string = "Spaces",
    color = colors.bg1,
  },
  background = {
    color = colors.with_alpha(colors.grey, 0.0),
    border_color = colors.with_alpha(colors.bg1, 0.0),
  }
})

spaces_indicator:subscribe("swap_menus_and_spaces", function(env)
  local currently_on = spaces_indicator:query().icon.value == icons.switch.on
  spaces_indicator:set({
    icon = currently_on and icons.switch.off or icons.switch.on
  })
end)

spaces_indicator:subscribe("mouse.entered", function(env)
  sbar.animate("tanh", 30, function()
    spaces_indicator:set({
      background = {
        color = { alpha = 1.0 },
        border_color = { alpha = 1.0 },
      },
      icon = { color = colors.bg1 },
      label = { width = "dynamic" }
    })
  end)
end)

spaces_indicator:subscribe("mouse.exited", function(env)
  sbar.animate("tanh", 30, function()
    spaces_indicator:set({
      background = {
        color = { alpha = 0.0 },
        border_color = { alpha = 0.0 },
      },
      icon = { color = colors.grey },
      label = { width = 0, }
    })
  end)
end)

spaces_indicator:subscribe("mouse.clicked", function(env)
  sbar.trigger("swap_menus_and_spaces")
end)