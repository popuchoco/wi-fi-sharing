// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "NativeWifiBridge",
    platforms: [.iOS(.v15)],
    products: [
        .library(name: "NativeWifiBridge", targets: ["NativeWifiBridge"])
    ],
    dependencies: [
        .package(url: "https://github.com/ionic-team/capacitor-swift-pm.git", from: "8.0.0")
    ],
    targets: [
        .target(
            name: "NativeWifiBridge",
            dependencies: [
                .product(name: "Capacitor", package: "capacitor-swift-pm")
            ],
            path: "ios/Sources/NativeWifiBridge",
            linkerSettings: [
                .linkedFramework("CoreLocation"),
                .linkedFramework("NetworkExtension")
            ]
        )
    ]
)
