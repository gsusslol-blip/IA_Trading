package app.gsuss.asistente

import android.content.Context
import android.net.wifi.WifiManager
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.SocketTimeoutException

/** Finds the PC on the same LAN via UDP broadcast (works with Ethernet on the PC). */
object LanFind {
    const val PORT = 8788
    private val probe = "ILARIA?".toByteArray(Charsets.UTF_8)
    private val magic = "ILARIA1".toByteArray(Charsets.UTF_8)

    fun find(context: Context, timeoutMs: Int = 2800): String? {
        val wifi = context.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        val lock = wifi.createMulticastLock("ilaria-find").apply {
            setReferenceCounted(false)
            acquire()
        }
        try {
            DatagramSocket().use { sock ->
                sock.broadcast = true
                sock.reuseAddress = true
                sock.soTimeout = 350
                val targets = destinations(wifi)
                val deadline = System.currentTimeMillis() + timeoutMs
                var lastSend = 0L
                while (System.currentTimeMillis() < deadline) {
                    val now = System.currentTimeMillis()
                    if (now - lastSend > 450) {
                        for (addr in targets) {
                            try {
                                sock.send(DatagramPacket(probe, probe.size, addr, PORT))
                            } catch (_: Exception) {
                            }
                        }
                        lastSend = now
                    }
                    try {
                        val buf = ByteArray(512)
                        val pkt = DatagramPacket(buf, buf.size)
                        sock.receive(pkt)
                        parse(pkt.data, pkt.length)?.let { return it }
                    } catch (_: SocketTimeoutException) {
                    }
                }
            }
        } catch (_: Exception) {
            return null
        } finally {
            if (lock.isHeld) lock.release()
        }
        return null
    }

    private fun parse(data: ByteArray, length: Int): String? {
        if (length < magic.size + 8) return null
        for (i in magic.indices) {
            if (data[i] != magic[i]) return null
        }
        val json = String(data, magic.size, length - magic.size, Charsets.UTF_8)
        return try {
            val obj = JSONObject(json)
            if (obj.optString("app") != "Ilaria") return null
            val url = obj.optString("url").trim().trimEnd('/')
            if (url.startsWith("http://") || url.startsWith("https://")) url else null
        } catch (_: Exception) {
            null
        }
    }

    private fun destinations(wifi: WifiManager): List<InetAddress> {
        val out = linkedSetOf<InetAddress>()
        try {
            out.add(InetAddress.getByName("255.255.255.255"))
        } catch (_: Exception) {
        }
        try {
            val dhcp = wifi.dhcpInfo
            if (dhcp != null && dhcp.ipAddress != 0 && dhcp.netmask != 0) {
                val bcast = (dhcp.ipAddress and dhcp.netmask) or dhcp.netmask.inv()
                out.add(InetAddress.getByAddress(ipv4(bcast)))
            }
        } catch (_: Exception) {
        }
        for (guess in listOf("192.168.1.255", "192.168.0.255", "10.0.0.255")) {
            try {
                out.add(InetAddress.getByName(guess))
            } catch (_: Exception) {
            }
        }
        return out.toList()
    }

    private fun ipv4(littleEndian: Int): ByteArray {
        return byteArrayOf(
            (littleEndian and 0xff).toByte(),
            (littleEndian shr 8 and 0xff).toByte(),
            (littleEndian shr 16 and 0xff).toByte(),
            (littleEndian shr 24 and 0xff).toByte(),
        )
    }
}
