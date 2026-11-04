import Foundation
import Security

// Keychain boundary for Python's `luvatrix_core.platform.ios.keychain`.
// rubicon-objc resolves the exported class name and calls the static methods;
// the ObjC selectors surface to Python as readSecret_ / writeSecret_forAccount_
// / deleteSecret_. Secrets are generic passwords accessible after first unlock
// on this device only, so tokens never migrate through backups or other devices.
@objc(LuvatrixKeychain)
final class KeychainBridge: NSObject {
    private static let service = "com.luvatrix.workos"

    @objc static func readSecret(_ account: String) -> NSString? {
        var query = baseQuery(account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess,
              let data = item as? Data,
              let value = String(data: data, encoding: .utf8) else {
            return nil
        }
        return value as NSString
    }

    @objc static func writeSecret(_ value: String, forAccount account: String) -> Bool {
        let data = Data(value.utf8)
        var attributes = baseQuery(account)
        attributes[kSecValueData as String] = data
        attributes[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        var status = SecItemAdd(attributes as CFDictionary, nil)
        if status == errSecDuplicateItem {
            status = SecItemUpdate(
                baseQuery(account) as CFDictionary,
                [kSecValueData as String: data] as CFDictionary
            )
        }
        if status != errSecSuccess {
            print("[ios-keychain] write failed for account \(account): OSStatus \(status)")
        }
        return status == errSecSuccess
    }

    @objc static func deleteSecret(_ account: String) -> Bool {
        let status = SecItemDelete(baseQuery(account) as CFDictionary)
        return status == errSecSuccess || status == errSecItemNotFound
    }

    private static func baseQuery(_ account: String) -> [String: Any] {
        return [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }
}
