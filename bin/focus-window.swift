import Cocoa
import Foundation

// MARK: - Constants

let VERSION = "1.0.0"
let PROGRAM_NAME = "focus-window"

// MARK: - Helper Structures

struct AeroMonitor: Codable {
    let monitorId: Int
    let monitorName: String

    enum CodingKeys: String, CodingKey {
        case monitorId = "monitor-id"
        case monitorName = "monitor-name"
    }
}

struct AeroWindow: Codable {
    let windowId: Int
    let monitorId: Int
    let appName: String

    enum CodingKeys: String, CodingKey {
        case windowId = "window-id"
        case monitorId = "monitor-id"
        case appName = "app-name"
    }
}

struct MonitorGeometry {
    let name: String
    let id: Int
    let frame: CGRect
}

enum Direction: String {
    case up, down, left, right
}

// MARK: - CLI Utilities

func printHelp() {
    print("""
\(PROGRAM_NAME) - Focus windows in any direction using accurate geometry

USAGE:
    \(PROGRAM_NAME) <DIRECTION> [OPTIONS]

DIRECTIONS:
    up          Focus window above (same or different monitor)
    down        Focus window below (same or different monitor)
    left        Focus window to the left (same or different monitor)
    right       Focus window to the right (same or different monitor)

OPTIONS:
    -h, --help      Show this help message
    -v, --version   Show version information
    --verbose       Show detailed information about window and monitor detection
    --debug         Show very detailed geometric calculations and decision logic

DESCRIPTION:
    This tool works around aerospace's bugs with directional focus by using both
    macOS's NSScreen API for monitor positioning and Accessibility API for window
    positions. It intelligently focuses windows based on actual geometry.

    The tool first checks for windows in the given direction on the same monitor.
    If none are found, it looks for windows on adjacent monitors. When focusing
    cross-monitor, it selects the window closest to the entry edge.

BEHAVIOR:
    - Same-monitor focus: Delegates to aerospace's built-in directional focus
    - Cross-monitor focus: Uses accurate monitor geometry to find target monitor,
      then focuses the first window or the monitor itself
    - Empty monitors: Focuses the monitor anyway (useful for mouse positioning)

EXAMPLES:
    # Focus window to the right
    \(PROGRAM_NAME) right

    # Focus window above with detailed output
    \(PROGRAM_NAME) up --verbose

    # Debug geometric calculations (helpful for troubleshooting)
    \(PROGRAM_NAME) up --debug

EXIT CODES:
    0    Success
    1    Error (invalid arguments, no monitor/window found, or aerospace failure)

INTEGRATION:
    Typically used with aerospace keybindings:
        cmd-h = 'exec-and-forget focus-window left'
        cmd-j = 'exec-and-forget focus-window down'
        cmd-k = 'exec-and-forget focus-window up'
        cmd-l = 'exec-and-forget focus-window right'
""")
}

func printVersion() {
    print("\(PROGRAM_NAME) version \(VERSION)")
}

// MARK: - Utilities

func exec(_ command: String) -> String? {
    let process = Process()
    let outPipe = Pipe()
    let errPipe = Pipe()

    process.executableURL = URL(fileURLWithPath: "/bin/bash")
    process.arguments = ["-c", command]
    process.standardOutput = outPipe
    process.standardError = errPipe
    process.standardInput = nil  // Explicitly set to nil to avoid blocking

    do {
        try process.run()
        process.waitUntilExit()

        guard process.terminationStatus == 0 else {
            return nil
        }

        let data = outPipe.fileHandleForReading.readDataToEndOfFile()
        let output = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)

        return output
    } catch {
        return nil
    }
}

// MARK: - Monitor Pattern Extraction

func getMonitorPattern(from name: String) -> String {
    // If name contains parentheses with a number like "C49HG9x (1)", extract just "(1)"
    // This uniquely identifies monitors with the same base name
    if let range = name.range(of: #"\(\d+\)$"#, options: .regularExpression) {
        return String(name[range])
    }

    // Otherwise, use the first word (usually unique)
    // e.g., "DeskPad Display" -> "DeskPad"
    let components = name.components(separatedBy: " ")
    return components.first ?? name
}

// MARK: - Overhang Detection

func hasVerticalOverhang(monitor1: MonitorGeometry, monitor2: MonitorGeometry) -> Bool {
    // Check if monitors are vertically stacked (have X-axis overlap)
    let xOverlap = min(monitor1.frame.maxX, monitor2.frame.maxX) - max(monitor1.frame.minX, monitor2.frame.minX)

    if xOverlap <= 0 {
        return false  // Not vertically stacked
    }

    // Check if there's horizontal offset (overhang)
    let leftOffset = abs(monitor1.frame.minX - monitor2.frame.minX)
    let rightOffset = abs(monitor1.frame.maxX - monitor2.frame.maxX)

    // If either edge is offset by more than a small threshold, there's overhang
    return leftOffset > 10 || rightOffset > 10
}

// MARK: - Direction Finding Logic for Monitors

func findMonitorInDirection(_ direction: Direction, current: MonitorGeometry, all: [MonitorGeometry]) -> MonitorGeometry? {
    let currentMinX = current.frame.minX
    let currentMaxX = current.frame.maxX
    let currentMinY = current.frame.minY
    let currentMaxY = current.frame.maxY

    var candidates: [(geometry: MonitorGeometry, distance: CGFloat)] = []

    for geometry in all where geometry.id != current.id {
        let monitorMinX = geometry.frame.minX
        let monitorMaxX = geometry.frame.maxX
        let monitorMinY = geometry.frame.minY
        let monitorMaxY = geometry.frame.maxY

        switch direction {
        case .up:
            // In NSScreen coordinates (Y increases upward):
            // Monitor is "above" if its bottom edge (minY) is >= our top edge (maxY)
            let xOverlap = min(currentMaxX, monitorMaxX) - max(currentMinX, monitorMinX)
            if monitorMinY >= currentMaxY && xOverlap > 0 {
                let distance = monitorMinY - currentMaxY
                candidates.append((geometry, distance))
            }

        case .down:
            // Monitor is "below" if its top edge (maxY) is <= our bottom edge (minY)
            let xOverlap = min(currentMaxX, monitorMaxX) - max(currentMinX, monitorMinX)
            if monitorMaxY <= currentMinY && xOverlap > 0 {
                let distance = currentMinY - monitorMaxY
                candidates.append((geometry, distance))
            }

        case .left:
            // Monitor is "left" if its right edge (maxX) is <= our left edge (minX)
            let yOverlap = min(currentMaxY, monitorMaxY) - max(currentMinY, monitorMinY)
            if monitorMaxX <= currentMinX && yOverlap > 0 {
                let distance = currentMinX - monitorMaxX
                candidates.append((geometry, distance))
            }

        case .right:
            // Monitor is "right" if its left edge (minX) is >= our right edge (maxX)
            let yOverlap = min(currentMaxY, monitorMaxY) - max(currentMinY, monitorMinY)
            if monitorMinX >= currentMaxX && yOverlap > 0 {
                let distance = monitorMinX - currentMaxX
                candidates.append((geometry, distance))
            }
        }
    }

    // Pick the closest monitor (smallest distance)
    return candidates.min(by: { $0.distance < $1.distance })?.geometry
}

// MARK: - Main Logic

func main() {
    // Parse command line arguments
    let args = CommandLine.arguments

    guard args.count > 1 else {
        fputs("Error: Missing direction argument\n\n", stderr)
        fputs("Usage: \(PROGRAM_NAME) <up|down|left|right> [OPTIONS]\n", stderr)
        fputs("Try '\(PROGRAM_NAME) --help' for more information.\n", stderr)
        exit(1)
    }

    // Check for help flag
    if args.contains("--help") || args.contains("-h") {
        printHelp()
        exit(0)
    }

    // Check for version flag
    if args.contains("--version") || args.contains("-v") {
        printVersion()
        exit(0)
    }

    // Check for verbose and debug flags
    let verbose = args.contains("--verbose")
    let debug = args.contains("--debug")

    // Get direction (first non-flag argument)
    guard let direction = Direction(rawValue: args[1]) else {
        fputs("Error: Invalid direction '\(args[1])'\n", stderr)
        fputs("Valid directions: up, down, left, right\n", stderr)
        fputs("Try '\(PROGRAM_NAME) --help' for more information.\n", stderr)
        exit(1)
    }

    if verbose || debug {
        print("[\(PROGRAM_NAME)] Focusing \(direction.rawValue)")
        if debug {
            print(String(repeating: "=", count: 80))
            print("DEBUG MODE - Detailed geometric calculations")
            print(String(repeating: "=", count: 80))
        }
    }

    // 1. Get focused window info from aerospace
    if verbose {
        print("[\(PROGRAM_NAME)] Getting focused window information from aerospace...")
    }

    guard let focusedWindowIdStr = exec("aerospace list-windows --focused --format '%{window-id}'"),
          let focusedWindowId = Int(focusedWindowIdStr) else {
        fputs("Error: Could not get focused window ID\n", stderr)
        fputs("Make sure a window is focused and aerospace is running.\n", stderr)
        exit(1)
    }

    guard let focusedMonitorIdStr = exec("aerospace list-windows --focused --format '%{monitor-id}'"),
          let focusedMonitorId = Int(focusedMonitorIdStr) else {
        fputs("Error: Could not get focused window's monitor ID\n", stderr)
        exit(1)
    }

    if verbose {
        print("[\(PROGRAM_NAME)] Focused window ID: \(focusedWindowId), monitor ID: \(focusedMonitorId)")
    }

    // 2. Get all aerospace windows
    if verbose {
        print("[\(PROGRAM_NAME)] Getting all aerospace windows...")
    }

    guard let aerospaceWindowsOutput = exec("aerospace list-windows --all --format '%{window-id}|%{monitor-id}|%{app-name}'") else {
        fputs("Error: Could not get aerospace windows\n", stderr)
        exit(1)
    }

    var aeroWindows: [AeroWindow] = []
    for line in aerospaceWindowsOutput.components(separatedBy: "\n") where !line.isEmpty {
        let parts = line.components(separatedBy: "|")
        if parts.count >= 3,
           let windowId = Int(parts[0]),
           let monitorId = Int(parts[1]) {
            aeroWindows.append(AeroWindow(
                windowId: windowId,
                monitorId: monitorId,
                appName: parts[2]
            ))
        }
    }

    if verbose {
        print("[\(PROGRAM_NAME)] Found \(aeroWindows.count) windows")
    }

    // 3. Get all aerospace monitors
    if verbose {
        print("[\(PROGRAM_NAME)] Getting aerospace monitors...")
    }

    guard let aerospaceJSON = exec("aerospace list-monitors --json"),
          let jsonData = aerospaceJSON.data(using: .utf8) else {
        fputs("Error: Could not get aerospace monitors\n", stderr)
        exit(1)
    }

    let aeroMonitors: [AeroMonitor]
    do {
        aeroMonitors = try JSONDecoder().decode([AeroMonitor].self, from: jsonData)
        if verbose {
            print("[\(PROGRAM_NAME)] Found \(aeroMonitors.count) monitors")
        }
    } catch {
        fputs("Error: Could not parse aerospace monitors JSON: \(error)\n", stderr)
        exit(1)
    }

    // 4. Get all NSScreen geometry
    if verbose {
        print("[\(PROGRAM_NAME)] Getting monitor geometry from NSScreen...")
    }

    let screens = NSScreen.screens
    var monitorGeometry: [MonitorGeometry] = []

    for screen in screens {
        let name = screen.localizedName

        // Find matching aerospace monitor
        if let aeroMonitor = aeroMonitors.first(where: { $0.monitorName == name }) {
            monitorGeometry.append(MonitorGeometry(
                name: name,
                id: aeroMonitor.monitorId,
                frame: screen.frame
            ))
        }
    }

    if verbose || debug {
        print("[\(PROGRAM_NAME)] Matched \(monitorGeometry.count) monitor geometries")
        for geometry in monitorGeometry {
            print("  - \(geometry.name) (ID: \(geometry.id)): \(geometry.frame)")
        }
    }

    if debug {
        print("\n" + String(repeating: "-", count: 80))
        print("CURRENT STATE")
        print(String(repeating: "-", count: 80))
        print("Focused Window ID: \(focusedWindowId)")
        print("Focused Monitor ID: \(focusedMonitorId)")
        if let currentMon = aeroMonitors.first(where: { $0.monitorId == focusedMonitorId }),
           let currentGeo = monitorGeometry.first(where: { $0.id == focusedMonitorId }) {
            print("Current Monitor: \(currentMon.monitorName)")
            print("  Position: origin=(\(currentGeo.frame.origin.x), \(currentGeo.frame.origin.y))")
            print("  Size: \(currentGeo.frame.size.width)×\(currentGeo.frame.size.height)")
            print("  Bounds: X=[\(currentGeo.frame.minX), \(currentGeo.frame.maxX)], Y=[\(currentGeo.frame.minY), \(currentGeo.frame.maxY)]")
        }
        print("\nDirection: \(direction.rawValue)")
        print("\nNOTE: NSScreen coordinates have Y increasing UPWARD (origin at bottom-left)")
        print(String(repeating: "-", count: 80))
    }

    // 5. First try aerospace's built-in directional focus (works well for same-monitor)
    if verbose {
        print("[\(PROGRAM_NAME)] Trying aerospace's built-in directional focus...")
    }

    let directionArg = direction.rawValue
    let aerospaceDirectionalCmd = "aerospace focus \(directionArg)"

    if debug {
        print("\n" + String(repeating: "-", count: 80))
        print("ATTEMPTING AEROSPACE BUILT-IN FOCUS")
        print(String(repeating: "-", count: 80))
        print("Command: \(aerospaceDirectionalCmd)")
    }

    if let result = exec(aerospaceDirectionalCmd), !result.isEmpty {
        // Check if focus changed by comparing window IDs
        if let newFocusedIdStr = exec("aerospace list-windows --focused --format '%{window-id}'"),
           let newFocusedId = Int(newFocusedIdStr),
           newFocusedId != focusedWindowId {

            // Get detailed info about the newly focused window
            let newMonitorIdStr = exec("aerospace list-windows --focused --format '%{monitor-id}'")
            let newMonitorId = newMonitorIdStr.flatMap { Int($0) }

            if debug {
                print("\n✓ Focus changed successfully")
                print("\nPRE-EXECUTION STATE:")
                print("  Window ID: \(focusedWindowId)")
                print("  Monitor ID: \(focusedMonitorId)")

                print("\nPOST-EXECUTION STATE:")
                print("  Window ID: \(newFocusedId)")
                if let monId = newMonitorId {
                    print("  Monitor ID: \(monId)")
                    if let monInfo = aeroMonitors.first(where: { $0.monitorId == monId }) {
                        print("  Monitor Name: \(monInfo.monitorName)")
                    }
                }
                if let newWindowInfo = aeroWindows.first(where: { $0.windowId == newFocusedId }) {
                    print("  App Name: \(newWindowInfo.appName)")
                }

                print("\n" + String(repeating: "=", count: 80))
                print("RESULT: Focus changed via aerospace built-in command")
                print(String(repeating: "=", count: 80))
            }

            // Focus changed successfully
            if verbose || !args.contains("--quiet") {
                if let newWindowInfo = aeroWindows.first(where: { $0.windowId == newFocusedId }) {
                    print("Focused window \(direction.rawValue): \(newWindowInfo.appName)")
                } else {
                    print("Focused window \(direction.rawValue)")
                }
            }
            exit(0)
        } else if debug {
            print("\n✗ Focus did not change (window ID still \(focusedWindowId))")
        }
    }

    if verbose {
        print("[\(PROGRAM_NAME)] Aerospace focus didn't change window, trying cross-monitor focus...")
    }

    // 6. Aerospace's focus didn't work, so we're likely trying to focus cross-monitor
    // Use our accurate monitor geometry to find the target monitor
    guard let currentMonitorGeometry = monitorGeometry.first(where: { $0.id == focusedMonitorId }) else {
        fputs("Error: Could not find geometry for current monitor\n", stderr)
        exit(1)
    }

    if debug {
        print("\n" + String(repeating: "-", count: 80))
        print("FINDING TARGET MONITOR IN DIRECTION: \(direction.rawValue)")
        print(String(repeating: "-", count: 80))
        print("Current monitor bounds: X=[\(currentMonitorGeometry.frame.minX), \(currentMonitorGeometry.frame.maxX)], Y=[\(currentMonitorGeometry.frame.minY), \(currentMonitorGeometry.frame.maxY)]")
        print("\nEvaluating each monitor as a candidate:\n")

        for geometry in monitorGeometry where geometry.id != currentMonitorGeometry.id {
            print("Monitor: \(geometry.name) (ID: \(geometry.id))")
            print("  Bounds: X=[\(geometry.frame.minX), \(geometry.frame.maxX)], Y=[\(geometry.frame.minY), \(geometry.frame.maxY)]")

            let currentMinX = currentMonitorGeometry.frame.minX
            let currentMaxX = currentMonitorGeometry.frame.maxX
            let currentMinY = currentMonitorGeometry.frame.minY
            let currentMaxY = currentMonitorGeometry.frame.maxY
            let monitorMinX = geometry.frame.minX
            let monitorMaxX = geometry.frame.maxX
            let monitorMinY = geometry.frame.minY
            let monitorMaxY = geometry.frame.maxY

            switch direction {
            case .up:
                let xOverlap = min(currentMaxX, monitorMaxX) - max(currentMinX, monitorMinX)
                print("  Check if above: monitorMinY (\(monitorMinY)) >= currentMaxY (\(currentMaxY))? \(monitorMinY >= currentMaxY)")
                print("  X-axis overlap: \(xOverlap) (min=\(min(currentMaxX, monitorMaxX)), max=\(max(currentMinX, monitorMinX)))")
                if monitorMinY >= currentMaxY && xOverlap > 0 {
                    let distance = monitorMinY - currentMaxY
                    print("  ✓ CANDIDATE - Distance: \(distance)")
                } else {
                    print("  ✗ Not a candidate - \(monitorMinY >= currentMaxY ? "overlap too small" : "not above")")
                }
            case .down:
                let xOverlap = min(currentMaxX, monitorMaxX) - max(currentMinX, monitorMinX)
                print("  Check if below: monitorMaxY (\(monitorMaxY)) <= currentMinY (\(currentMinY))? \(monitorMaxY <= currentMinY)")
                print("  X-axis overlap: \(xOverlap)")
                if monitorMaxY <= currentMinY && xOverlap > 0 {
                    let distance = currentMinY - monitorMaxY
                    print("  ✓ CANDIDATE - Distance: \(distance)")
                } else {
                    print("  ✗ Not a candidate - \(monitorMaxY <= currentMinY ? "overlap too small" : "not below")")
                }
            case .left:
                let yOverlap = min(currentMaxY, monitorMaxY) - max(currentMinY, monitorMinY)
                print("  Check if left: monitorMaxX (\(monitorMaxX)) <= currentMinX (\(currentMinX))? \(monitorMaxX <= currentMinX)")
                print("  Y-axis overlap: \(yOverlap)")
                if monitorMaxX <= currentMinX && yOverlap > 0 {
                    let distance = currentMinX - monitorMaxX
                    print("  ✓ CANDIDATE - Distance: \(distance)")
                } else {
                    print("  ✗ Not a candidate - \(monitorMaxX <= currentMinX ? "overlap too small" : "not to left")")
                }
            case .right:
                let yOverlap = min(currentMaxY, monitorMaxY) - max(currentMinY, monitorMinY)
                print("  Check if right: monitorMinX (\(monitorMinX)) >= currentMaxX (\(currentMaxX))? \(monitorMinX >= currentMaxX)")
                print("  Y-axis overlap: \(yOverlap)")
                if monitorMinX >= currentMaxX && yOverlap > 0 {
                    let distance = monitorMinX - currentMaxX
                    print("  ✓ CANDIDATE - Distance: \(distance)")
                } else {
                    print("  ✗ Not a candidate - \(monitorMinX >= currentMaxX ? "overlap too small" : "not to right")")
                }
            }
            print("")
        }
    }

    guard let targetMonitor = findMonitorInDirection(direction, current: currentMonitorGeometry, all: monitorGeometry) else {
        fputs("Error: No monitor or window found \(direction.rawValue)\n", stderr)
        if verbose {
            fputs("This could mean:\n", stderr)
            fputs("  - There is no monitor in that direction\n", stderr)
            fputs("  - The monitors don't have sufficient overlap for proper positioning\n", stderr)
        }
        exit(1)
    }

    if verbose || debug {
        print("[\(PROGRAM_NAME)] Target monitor: '\(targetMonitor.name)' (ID: \(targetMonitor.id))")
    }

    if debug {
        print(String(repeating: "-", count: 80))
        print("SELECTED TARGET: \(targetMonitor.name) (ID: \(targetMonitor.id))")
        print("Target bounds: X=[\(targetMonitor.frame.minX), \(targetMonitor.frame.maxX)], Y=[\(targetMonitor.frame.minY), \(targetMonitor.frame.maxY)]")
        print(String(repeating: "-", count: 80))
    }

    // 7. Focus the target monitor (aerospace will decide which window gets focus)
    // NOTE: We use focus-monitor instead of focus --window-id because aerospace's
    // window-id focus is buggy and often focuses the wrong window
    let targetMonitorWindows = aeroWindows.filter { $0.monitorId == targetMonitor.id }

    if debug {
        print("\n" + String(repeating: "-", count: 80))
        print("ATTEMPTING CROSS-MONITOR FOCUS")
        print(String(repeating: "-", count: 80))
        print("Target Monitor: \(targetMonitor.name) (ID: \(targetMonitor.id))")
        print("Windows on target monitor: \(targetMonitorWindows.count)")
        if !targetMonitorWindows.isEmpty {
            print("Available windows:")
            for window in targetMonitorWindows {
                print("  - \(window.appName) (ID: \(window.windowId))")
            }
        }
        print("\nNOTE: Using 'focus-monitor' instead of 'focus --window-id'")
        print("      because aerospace's window-id focus is buggy")
    }

    if verbose && !debug {
        print("[\(PROGRAM_NAME)] Found \(targetMonitorWindows.count) windows on target monitor")
        print("[\(PROGRAM_NAME)] Focusing monitor \(targetMonitor.name)")
    }

    // Detect if we need to reverse direction due to overhang
    var effectiveDirection = direction
    let hasOverhang = hasVerticalOverhang(monitor1: currentMonitorGeometry, monitor2: targetMonitor)

    if hasOverhang && (direction == .up || direction == .down) {
        // Reverse up/down when overhang detected
        effectiveDirection = (direction == .up) ? .down : .up

        if debug {
            print("\nOVERHANG DETECTED - Reversing vertical direction")
            print("  Original direction: \(direction.rawValue)")
            print("  Effective direction for aerospace: \(effectiveDirection.rawValue)")
        }
    }

    let focusMonitorCommand = "aerospace focus-monitor \(effectiveDirection.rawValue)"

    if debug {
        print("Command: \(focusMonitorCommand)")
        if hasOverhang {
            print("NOTE: Using reversed direction (\(effectiveDirection.rawValue)) due to monitor overhang")
        }
    }

    if exec(focusMonitorCommand) != nil {
        // Verify what actually got focused
        if let newFocusedIdStr = exec("aerospace list-windows --focused --format '%{window-id}'"),
           let newFocusedId = Int(newFocusedIdStr) {

            let newMonitorIdStr = exec("aerospace list-windows --focused --format '%{monitor-id}'")
            let newMonitorId = newMonitorIdStr.flatMap { Int($0) }

            if debug {
                print("\nPOST-EXECUTION STATE:")
                print("  Window ID: \(newFocusedId)")
                if let monId = newMonitorId {
                    print("  Monitor ID: \(monId)")
                    if let monInfo = aeroMonitors.first(where: { $0.monitorId == monId }) {
                        print("  Monitor Name: \(monInfo.monitorName)")
                    }
                }
                if let newWindowInfo = aeroWindows.first(where: { $0.windowId == newFocusedId }) {
                    print("  App Name: \(newWindowInfo.appName)")
                }

                print("\nVERIFICATION:")
                if newMonitorId == targetMonitor.id {
                    print("  ✓ SUCCESS - Focus moved to target monitor \(targetMonitor.id)")
                    if let focusedWindow = aeroWindows.first(where: { $0.windowId == newFocusedId }) {
                        print("  Focused window: \(focusedWindow.appName)")
                    }
                } else {
                    print("  ✗ MISMATCH - Expected monitor \(targetMonitor.id) but got \(newMonitorId ?? -1)")
                    if let actualMonitor = aeroMonitors.first(where: { $0.monitorId == newMonitorId ?? -1 }) {
                        print("  Actual monitor: \(actualMonitor.monitorName)")
                    }
                }

                print("\n" + String(repeating: "=", count: 80))
                print("RESULT: Cross-monitor focus completed")
                print(String(repeating: "=", count: 80))
            }
        }

        if verbose || !args.contains("--quiet") {
            if let newWindowInfo = aeroWindows.first(where: { $0.windowId == exec("aerospace list-windows --focused --format '%{window-id}'").flatMap { Int($0) } ?? -1 }) {
                print("Focused \(direction.rawValue) to monitor \(targetMonitor.name): \(newWindowInfo.appName)")
            } else {
                print("Focused \(direction.rawValue) to monitor \(targetMonitor.name)")
            }
        }
        exit(0)
    } else {
        fputs("Error: Failed to execute aerospace focus-monitor command\n", stderr)
        fputs("Command: \(focusMonitorCommand)\n", stderr)
        exit(1)
    }
}

main()
