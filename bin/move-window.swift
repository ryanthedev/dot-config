import Cocoa
import Foundation

// MARK: - Constants

let VERSION = "1.0.0"
let PROGRAM_NAME = "move-window"

// MARK: - Helper Structures

struct AeroMonitor: Codable {
    let monitorId: Int
    let monitorName: String

    enum CodingKeys: String, CodingKey {
        case monitorId = "monitor-id"
        case monitorName = "monitor-name"
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
\(PROGRAM_NAME) - Move focused window between monitors using accurate geometry

USAGE:
    \(PROGRAM_NAME) <DIRECTION> [OPTIONS]

DIRECTIONS:
    up          Move window to monitor above current monitor
    down        Move window to monitor below current monitor
    left        Move window to monitor left of current monitor
    right       Move window to monitor right of current monitor

OPTIONS:
    -h, --help      Show this help message
    -v, --version   Show version information
    --verbose       Show detailed information about monitor detection
    --debug         Show very detailed geometric calculations and decision logic

DESCRIPTION:
    This tool works around aerospace's bugs with monitor positioning by using
    macOS's NSScreen API to determine actual physical monitor layouts. It then
    moves the focused window to the correct monitor in the specified direction.

    The tool uses spatial reasoning with overlap detection to find the nearest
    monitor in the given direction, ensuring windows move to the expected display.

EXAMPLES:
    # Move focused window to the monitor on the right
    \(PROGRAM_NAME) right

    # Move focused window up with verbose output
    \(PROGRAM_NAME) up --verbose

    # Debug geometric calculations (helpful for troubleshooting)
    \(PROGRAM_NAME) up --debug

EXIT CODES:
    0    Success
    1    Error (invalid arguments, no monitor found, or aerospace failure)

INTEGRATION:
    Typically used with aerospace keybindings:
        cmd-shift-h = 'exec-and-forget move-window left'
        cmd-shift-j = 'exec-and-forget move-window down'
        cmd-shift-k = 'exec-and-forget move-window up'
        cmd-shift-l = 'exec-and-forget move-window right'
""")
}

func printVersion() {
    print("\(PROGRAM_NAME) version \(VERSION)")
}

// MARK: - Utilities

func exec(_ command: String) -> String? {
    let process = Process()
    let pipe = Pipe()

    process.executableURL = URL(fileURLWithPath: "/bin/bash")
    process.arguments = ["-c", command]
    process.standardOutput = pipe
    process.standardError = pipe

    do {
        try process.run()
        process.waitUntilExit()

        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let output = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)

        return output
    } catch {
        return nil
    }
}

// MARK: - Direction Finding Logic

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
        print("[\(PROGRAM_NAME)] Moving window \(direction.rawValue)")
        if debug {
            print(String(repeating: "=", count: 80))
            print("DEBUG MODE - Detailed geometric calculations")
            print(String(repeating: "=", count: 80))
        }
    }

    // 1. Get focused window's monitor ID from aerospace
    if verbose {
        print("[\(PROGRAM_NAME)] Getting focused window information from aerospace...")
    }

    guard let focusedMonitorIdStr = exec("aerospace list-windows --focused --format '%{monitor-id}'"),
          let focusedMonitorId = Int(focusedMonitorIdStr) else {
        fputs("Error: Could not get focused window's monitor ID\n", stderr)
        fputs("Make sure a window is focused and aerospace is running.\n", stderr)
        exit(1)
    }

    if verbose {
        print("[\(PROGRAM_NAME)] Focused window is on monitor ID: \(focusedMonitorId)")
    }

    // 2. Get all aerospace monitors
    guard let aerospaceJSON = exec("aerospace list-monitors --json"),
          let jsonData = aerospaceJSON.data(using: .utf8) else {
        fputs("Error: Could not get aerospace monitors\n", stderr)
        exit(1)
    }

    let aeroMonitors: [AeroMonitor]
    do {
        aeroMonitors = try JSONDecoder().decode([AeroMonitor].self, from: jsonData)
    } catch {
        fputs("Error: Could not parse aerospace monitors JSON: \(error)\n", stderr)
        exit(1)
    }

    // Find current monitor name
    guard let currentMonitor = aeroMonitors.first(where: { $0.monitorId == focusedMonitorId }) else {
        fputs("Error: Could not find monitor with ID \(focusedMonitorId)\n", stderr)
        exit(1)
    }

    // 3. Get all NSScreen geometry
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

    // Find current monitor geometry
    guard let currentGeometry = monitorGeometry.first(where: { $0.id == focusedMonitorId }) else {
        fputs("Error: Could not find geometry for monitor '\(currentMonitor.monitorName)'\n", stderr)
        exit(1)
    }

    if verbose || debug {
        print("[\(PROGRAM_NAME)] Current monitor: '\(currentMonitor.monitorName)'")
        if !debug {
            print("[\(PROGRAM_NAME)] Monitor geometry: \(currentGeometry.frame)")
        }
        print("[\(PROGRAM_NAME)] Available monitors:")
        for geometry in monitorGeometry {
            print("  - \(geometry.name) (ID: \(geometry.id)): \(geometry.frame)")
        }
    }

    if debug {
        print("\n" + String(repeating: "-", count: 80))
        print("CURRENT STATE")
        print(String(repeating: "-", count: 80))
        print("Focused Monitor: \(currentMonitor.monitorName) (ID: \(focusedMonitorId))")
        print("  Position: origin=(\(currentGeometry.frame.origin.x), \(currentGeometry.frame.origin.y))")
        print("  Size: \(currentGeometry.frame.size.width)×\(currentGeometry.frame.size.height)")
        print("  Bounds: X=[\(currentGeometry.frame.minX), \(currentGeometry.frame.maxX)], Y=[\(currentGeometry.frame.minY), \(currentGeometry.frame.maxY)]")
        print("\nDirection: \(direction.rawValue)")
        print("\nNOTE: NSScreen coordinates have Y increasing UPWARD (origin at bottom-left)")
        print(String(repeating: "-", count: 80))
    }

    // 4. Find monitor in the specified direction
    if verbose && !debug {
        print("[\(PROGRAM_NAME)] Finding monitor \(direction.rawValue) of current monitor...")
    }

    if debug {
        print("\n" + String(repeating: "-", count: 80))
        print("FINDING TARGET MONITOR IN DIRECTION: \(direction.rawValue)")
        print(String(repeating: "-", count: 80))
        print("Current monitor bounds: X=[\(currentGeometry.frame.minX), \(currentGeometry.frame.maxX)], Y=[\(currentGeometry.frame.minY), \(currentGeometry.frame.maxY)]")
        print("\nEvaluating each monitor as a candidate:\n")

        for geometry in monitorGeometry where geometry.id != currentGeometry.id {
            print("Monitor: \(geometry.name) (ID: \(geometry.id))")
            print("  Bounds: X=[\(geometry.frame.minX), \(geometry.frame.maxX)], Y=[\(geometry.frame.minY), \(geometry.frame.maxY)]")

            let currentMinX = currentGeometry.frame.minX
            let currentMaxX = currentGeometry.frame.maxX
            let currentMinY = currentGeometry.frame.minY
            let currentMaxY = currentGeometry.frame.maxY
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

    guard let targetMonitor = findMonitorInDirection(direction, current: currentGeometry, all: monitorGeometry) else {
        fputs("Error: No monitor found \(direction.rawValue) of '\(currentMonitor.monitorName)'\n", stderr)
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

    // 5. Move window to target monitor using aerospace
    let moveCommand = "aerospace move-node-to-monitor --focus-follows-window \(targetMonitor.id)"

    if verbose {
        print("[\(PROGRAM_NAME)] Executing: \(moveCommand)")
    }

    if exec(moveCommand) != nil {
        if verbose || !args.contains("--quiet") {
            print("Moved window \(direction.rawValue) from '\(currentMonitor.monitorName)' to '\(targetMonitor.name)'")
        }
    } else {
        fputs("Error: Failed to execute aerospace move command\n", stderr)
        fputs("Command: \(moveCommand)\n", stderr)
        exit(1)
    }
}

main()
