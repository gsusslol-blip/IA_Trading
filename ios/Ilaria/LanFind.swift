import Foundation

/// Finds the PC on the same LAN via UDP broadcast (parity with Android LanFind).
enum LanFind {
    static let port: UInt16 = 8788
    private static let probe = Data("ILARIA_IOS_DISCOVER".utf8)
    private static let magic = Data("ILARIA1".utf8)
    private static let ackIos = "ILARIA_IOS_SERVER_ACK"

    /// Blocking discovery (call off the main actor). Returns HUD base URL or nil.
    static func find(timeoutMs: Int = 2800) -> String? {
        let sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
        guard sock >= 0 else { return nil }
        defer { close(sock) }

        var yes: Int32 = 1
        setsockopt(sock, SOL_SOCKET, SO_BROADCAST, &yes, socklen_t(MemoryLayout.size(ofValue: yes)))
        var tv = timeval(tv_sec: 0, tv_usec: 350_000)
        setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, socklen_t(MemoryLayout.size(ofValue: tv)))

        let destinations = Self.broadcastTargets()
        let deadline = Date().addingTimeInterval(Double(timeoutMs) / 1000.0)
        var lastSend = Date.distantPast
        var fallbackIP: String?

        while Date() < deadline {
            if Date().timeIntervalSince(lastSend) > 0.45 {
                for dest in destinations {
                    probe.withUnsafeBytes { raw in
                        guard let base = raw.bindMemory(to: UInt8.self).baseAddress else { return }
                        _ = dest.withSockAddr { addr, len in
                            sendto(sock, base, probe.count, 0, addr, len)
                        }
                    }
                }
                lastSend = Date()
            }
            var buf = [UInt8](repeating: 0, count: 512)
            var from = sockaddr_in()
            var fromLen = socklen_t(MemoryLayout<sockaddr_in>.size)
            let n = withUnsafeMutablePointer(to: &from) { ptr -> Int in
                ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { sa in
                    Int(recvfrom(sock, &buf, buf.count, 0, sa, &fromLen))
                }
            }
            guard n > 0 else { continue }
            let packet = Data(buf.prefix(n))
            if let url = parseMagic(packet) {
                return url
            }
            if let text = String(data: packet, encoding: .utf8), text.hasPrefix(ackIos) {
                fallbackIP = ipv4String(from)
            }
        }
        if let ip = fallbackIP, !ip.isEmpty, ip != "0.0.0.0" {
            return "http://\(ip):8787"
        }
        return nil
    }

    private static func parseMagic(_ data: Data) -> String? {
        guard data.count >= magic.count + 8 else { return nil }
        guard data.prefix(magic.count) == magic else { return nil }
        let jsonData = data.dropFirst(magic.count)
        guard let obj = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
              (obj["app"] as? String) == "Ilaria",
              let url = obj["url"] as? String
        else { return nil }
        var trimmed = url.trimmingCharacters(in: .whitespacesAndNewlines)
        while trimmed.hasSuffix("/") { trimmed.removeLast() }
        if trimmed.hasPrefix("http://") || trimmed.hasPrefix("https://") {
            return trimmed
        }
        return nil
    }

    private static func ipv4String(_ addr: sockaddr_in) -> String {
        var copy = addr
        var buf = [CChar](repeating: 0, count: Int(INET_ADDRSTRLEN))
        inet_ntop(AF_INET, &copy.sin_addr, &buf, socklen_t(INET_ADDRSTRLEN))
        return String(cString: buf)
    }

    private static func broadcastTargets() -> [SockDest] {
        [
            SockDest(host: "255.255.255.255", port: port),
            SockDest(host: "192.168.1.255", port: port),
            SockDest(host: "192.168.0.255", port: port),
            SockDest(host: "10.0.0.255", port: port),
        ]
    }
}

private struct SockDest {
    let host: String
    let port: UInt16

    func withSockAddr<T>(_ body: (UnsafePointer<sockaddr>, socklen_t) -> T) -> T {
        var addr = sockaddr_in()
        addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = port.bigEndian
        inet_pton(AF_INET, host, &addr.sin_addr)
        return withUnsafePointer(to: &addr) { ptr in
            ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { sa in
                body(sa, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
    }
}
