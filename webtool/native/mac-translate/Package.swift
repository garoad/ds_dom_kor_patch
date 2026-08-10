// swift-tools-version:6.2
import PackageDescription

let package = Package(
    name: "mac-translate",
    platforms: [.macOS(.v26)],
    targets: [
        .executableTarget(name: "mac-translate", path: "Sources/mac-translate")
    ]
)
