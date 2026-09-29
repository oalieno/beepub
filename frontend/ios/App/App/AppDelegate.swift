import UIKit
import Capacitor

@UIApplicationMain
class AppDelegate: UIResponder, UIApplicationDelegate {

    var window: UIWindow?

    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
        // Override point for customization after application launch.
        return true
    }

    func applicationWillResignActive(_ application: UIApplication) {
        // Sent when the application is about to move from active to inactive state. This can occur for certain types of temporary interruptions (such as an incoming phone call or SMS message) or when the user quits the application and it begins the transition to the background state.
        // Use this method to pause ongoing tasks, disable timers, and invalidate graphics rendering callbacks. Games should use this method to pause the game.
    }

    func applicationDidEnterBackground(_ application: UIApplication) {
        // Use this method to release shared resources, save user data, invalidate timers, and store enough application state information to restore your application to its current state in case it is terminated later.
        // If your application supports background execution, this method is called instead of applicationWillTerminate: when the user quits.
    }

    func applicationWillEnterForeground(_ application: UIApplication) {
        // Called as part of the transition from the background to the active state; here you can undo many of the changes made on entering the background.
    }

    func applicationDidBecomeActive(_ application: UIApplication) {
        // Restart any tasks that were paused (or not yet started) while the application was inactive. If the application was previously in the background, optionally refresh the user interface.
    }

    func applicationWillTerminate(_ application: UIApplication) {
        // Called when the application is about to terminate. Save data if appropriate. See also applicationDidEnterBackground:.
    }

    func application(_ app: UIApplication, open url: URL, options: [UIApplication.OpenURLOptionsKey: Any] = [:]) -> Bool {
        // A book handed over by Files / the share sheet / AirDrop.
        if url.isFileURL, receiveOpenedBook(url) {
            return true
        }
        // Called when the app was launched with a url. Feel free to add additional processing here,
        // but if you want the App API to support tracking app url opens, make sure to keep this call
        return ApplicationDelegateProxy.shared.application(app, open: url, options: options)
    }

    // MARK: - Books opened from other apps

    /// What the server's upload accepts (see CFBundleDocumentTypes in Info.plist
    /// and SERVER_FORMATS in src/lib/services/openedFiles.ts).
    private static let bookExtensions: Set<String> = ["epub", "txt", "mobi", "azw3", "cbz"]
    /// Caches/opened-books, read by the web app through the Filesystem plugin
    /// (Directory.Cache). Must match INBOX in openedFiles.ts.
    private static let openedBooksFolder = "opened-books"

    /// Copy the file into the app's own sandbox, where the web app picks it up
    /// (when it starts, or at once through the window event). The web side
    /// decides where it goes: the device library or a server library.
    private func receiveOpenedBook(_ url: URL) -> Bool {
        guard Self.bookExtensions.contains(url.pathExtension.lowercased()) else { return false }
        let fm = FileManager.default
        guard let caches = fm.urls(for: .cachesDirectory, in: .userDomainMask).first else { return false }
        let folder = caches.appendingPathComponent(Self.openedBooksFolder, isDirectory: true)

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

        // App already running: tell the page. On a cold start the page isn't
        // loaded yet and the event is lost; it scans the folder when it starts.
        if let bridge = (window?.rootViewController as? CAPBridgeViewController)?.bridge {
            bridge.triggerWindowJSEvent(eventName: "beepubFileOpened")
        }
        return true
    }

    func application(_ application: UIApplication, continue userActivity: NSUserActivity, restorationHandler: @escaping ([UIUserActivityRestoring]?) -> Void) -> Bool {
        // Called when the app was launched with an activity, including Universal Links.
        // Feel free to add additional processing here, but if you want the App API to support
        // tracking app url opens, make sure to keep this call
        return ApplicationDelegateProxy.shared.application(application, continue: userActivity, restorationHandler: restorationHandler)
    }

}
