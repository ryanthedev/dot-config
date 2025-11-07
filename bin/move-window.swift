import Cocoa
import Foundation

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
    guard CommandLine.arguments.count > 1 else {
        fputs("Usage: move-window <up|down|left|right>\n", stderr)
        exit(1)
    }

    guard let direction = Direction(rawValue: CommandLine.arguments[1]) else {
        fputs("Error: Invalid direction. Use: up, down, left, or right\n", stderr)
        exit(1)
    }

    // 1. Get focused window's monitor ID from aerospace
    guard let focusedMonitorIdStr = exec("aerospace list-windows --focused --format '%{monitor-id}'"),
          let focusedMonitorId = Int(focusedMonitorIdStr) else {
        fputs("Error: Could not get focused window's monitor ID\n", stderr)
        exit(1)
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

    // 4. Find monitor in the specified direction
    guard let targetMonitor = findMonitorInDirection(direction, current: currentGeometry, all: monitorGeometry) else {
        fputs("No monitor found \(direction.rawValue) of '\(currentMonitor.monitorName)'\n", stderr)
        exit(1)
    }

    // 5. Move window to target monitor using aerospace
    let moveCommand = "aerospace move-node-to-monitor --focus-follows-window \(targetMonitor.id)"
    if exec(moveCommand) != nil {
        print("Moved window \(direction.rawValue) from '\(currentMonitor.monitorName)' to '\(targetMonitor.name)'")
    } else {
        fputs("Error: Failed to execute aerospace move command\n", stderr)
        exit(1)
    }
}

main()
