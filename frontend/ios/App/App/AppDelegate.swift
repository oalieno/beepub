import UIKit
import Capacitor

@UIApplicationMain
class AppDelegate: UIResponder, UIApplicationDelegate {

    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
        // Override point for customization after application launch.
        return true
    }

    // The window, opened URLs and universal links belong to the scene
    // (SceneDelegate below): under the scene lifecycle iOS no longer calls the
    // application(_:open:options:) and application(_:continue:) of this class.
}

/// The app's one window. Here rather than in its own file so the Xcode project
/// needs no new entry; Info.plist names it in UIApplicationSceneManifest.
class SceneDelegate: UIResponder, UIWindowSceneDelegate {

    /// Set by UIKit from Main.storyboard (UISceneStoryboardFile).
    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        // Launched by opening a book: the page isn't loaded yet; it scans the
        // folder when it starts.
        open(connectionOptions.urlContexts, notify: false)
        for userActivity in connectionOptions.userActivities {
            self.scene(scene, continue: userActivity)
        }
    }

    func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
        open(URLContexts, notify: true)
    }

    func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
        // Universal links, passed on to Capacitor as the app delegate used to.
        _ = ApplicationDelegateProxy.shared.application(UIApplication.shared, continue: userActivity) { _ in }
    }

    private func open(_ contexts: Set<UIOpenURLContext>, notify: Bool) {
        var received = false
        for context in contexts {
            let url = context.url
            // A book handed over by Files / the share sheet / AirDrop.
            if url.isFileURL, OpenedBooks.receive(url) {
                received = true
                continue
            }
            var options: [UIApplication.OpenURLOptionsKey: Any] = [:]
            if let source = context.options.sourceApplication {
                options[.sourceApplication] = source
            }
            _ = ApplicationDelegateProxy.shared.application(UIApplication.shared, open: url, options: options)
        }
        // App already running: tell the page.
        if received, notify, let bridge = (window?.rootViewController as? CAPBridgeViewController)?.bridge {
            bridge.triggerWindowJSEvent(eventName: "beepubFileOpened")
        }
    }
}

// MARK: - Books opened from other apps

enum OpenedBooks {
    /// What the server's upload accepts (see CFBundleDocumentTypes in Info.plist
    /// and SERVER_FORMATS in src/lib/services/openedFiles.ts).
    private static let bookExtensions: Set<String> = ["epub", "txt", "mobi", "azw3", "cbz"]
    /// Caches/opened-books, read by the web app through the Filesystem plugin
    /// (Directory.Cache). Must match INBOX in openedFiles.ts.
    private static let openedBooksFolder = "opened-books"

    /// Copy the file into the app's own sandbox, where the web app picks it up
    /// (when it starts, or at once through the window event). The web side
    /// decides where it goes: the device library or a server library.
    static func receive(_ url: URL) -> Bool {
        guard bookExtensions.contains(url.pathExtension.lowercased()) else { return false }
        let fm = FileManager.default
        guard let caches = fm.urls(for: .cachesDirectory, in: .userDomainMask).first else { return false }
        let folder = caches.appendingPathComponent(openedBooksFolder, isDirectory: true)

        // A file opened in place (iCloud Drive, another app's container) needs
        // security-scoped access; a copy iOS already put in Documents/Inbox does
        // not, and then this is a harmless false.
        let scoped = url.startAccessingSecurityScopedResource()
        defer {
            if scoped { url.stopAccessingSecurityScopedResource() }
        }

        // "<millis>-<short id>_<original name>": sorts by arrival, never collides,
        // and the web side recovers the name after the first "_".
        let stamp = Int(Date().timeIntervalSince1970 * 1000)
        let shortId = UUID().uuidString.prefix(8)
        let dest = folder.appendingPathComponent("\(stamp)-\(shortId)_\(url.lastPathComponent)")

        var copyError: Error?
        var coordinatorError: NSError?
        do {
            try fm.createDirectory(at: folder, withIntermediateDirectories: true)
            // A coordinated read makes iCloud download the file first.
            NSFileCoordinator().coordinate(readingItemAt: url, options: [.withoutChanges], error: &coordinatorError) { readURL in
                do {
                    try fm.copyItem(at: readURL, to: dest)
                } catch {
                    copyError = error
                }
            }
        } catch {
            copyError = error
        }
        if let error = copyError ?? coordinatorError {
            NSLog("BeePub: could not receive \(url.lastPathComponent): \(error)")
            return false
        }

        // A copy iOS made for us in Documents/Inbox is ours to clean up.
        if url.deletingLastPathComponent().lastPathComponent == "Inbox" {
            try? fm.removeItem(at: url)
        }
        return true
    }
}
