// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "eme-probe",
    platforms: [.macOS(.v12)],
    targets: [
        .executableTarget(
            name: "eme-probe",
            path: "Sources/eme-probe"
        )
    ]
)
