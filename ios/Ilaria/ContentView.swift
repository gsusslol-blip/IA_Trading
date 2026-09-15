import SwiftUI

struct Bubble: Identifiable {
    let id = UUID()
    let mine: Bool
    let text: String
}

struct ContentView: View {
    @EnvironmentObject private var prefs: Prefs
    @State private var brain: Brain?
    @State private var log: [Bubble] = []
    @State private var draft = ""
    @State private var busy = false
    @State private var showProfile = false
    @State private var status = "Listo"

    var body: some View {
        ZStack {
            Color(red: 0.04, green: 0.04, blue: 0.04).ignoresSafeArea()
            VStack(spacing: 0) {
                HStack {
                    Text("ILARIA")
                        .font(.system(size: 22, weight: .bold, design: .rounded))
                        .foregroundStyle(Color(red: 1, green: 0.16, blue: 0.33))
                    Spacer()
                    Text(status)
                        .font(.caption)
                        .foregroundStyle(.white.opacity(0.55))
                    Button("Perfil") { showProfile = true }
                        .font(.caption.weight(.semibold))
                }
                .padding()

                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 10) {
                            ForEach(log) { b in
                                Text(b.text)
                                    .foregroundStyle(.white)
                                    .padding(12)
                                    .frame(maxWidth: .infinity, alignment: b.mine ? .trailing : .leading)
                                    .background(
                                        RoundedRectangle(cornerRadius: 14)
                                            .fill(b.mine ? Color.white.opacity(0.08) : Color(red: 1, green: 0.16, blue: 0.33).opacity(0.18))
                                    )
                                    .id(b.id)
                            }
                        }
                        .padding(.horizontal)
                    }
                    .onChange(of: log.count) { _, _ in
                        if let last = log.last?.id {
                            withAnimation { proxy.scrollTo(last, anchor: .bottom) }
                        }
                    }
                }

                HStack(spacing: 8) {
                    TextField("escribe una frase", text: $draft)
                        .textFieldStyle(.plain)
                        .padding(12)
                        .background(RoundedRectangle(cornerRadius: 12).fill(Color.white.opacity(0.08)))
                        .foregroundStyle(.white)
                        .disabled(busy)
                    Button("OK") { Task { await send() } }
                        .buttonStyle(.borderedProminent)
                        .tint(Color(red: 1, green: 0.16, blue: 0.33))
                        .disabled(busy || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
                .padding()
            }
        }
        .sheet(isPresented: $showProfile) {
            ProfileSheet()
                .environmentObject(prefs)
        }
        .onAppear {
            if brain == nil { brain = Brain(prefs: prefs) }
            UIDevice.current.isBatteryMonitoringEnabled = true
        }
    }

    private func send() async {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        draft = ""
        log.append(Bubble(mine: true, text: text))
        busy = true
        status = "…"
        defer { busy = false }
        do {
            let engine = brain ?? Brain(prefs: prefs)
            brain = engine
            let out = try await engine.chat(text)
            for item in out.phone {
                switch PhoneHands.run(item) {
                case "clear_http":
                    break
                case "screenshot_hint":
                    status = "Captura: lateral + vol ▲"
                case "lock_hint":
                    status = "Bloqueo: botón lateral"
                case "volume_hint":
                    status = "Volumen: botones laterales"
                case let s? where s.hasPrefix("clipboard:"):
                    let clip = String(s.dropFirst("clipboard:".count))
                    let body = clip.isEmpty ? "(vacío)" : clip
                    log.append(Bubble(mine: false, text: "Portapapeles: \(body)"))
                default:
                    break
                }
            }
            log.append(Bubble(mine: false, text: out.text))
            SoloTts.speak(out.text)
            status = out.fromPc ? "PC" : "local"
        } catch {
            if let local = PhoneLocal.handle(raw: text, prefs: prefs) {
                for item in local.phone { _ = PhoneHands.run(item) }
                log.append(Bubble(mine: false, text: local.text))
            } else {
                log.append(Bubble(mine: false, text: error.localizedDescription))
            }
            status = "error"
        }
    }
}

struct ProfileSheet: View {
    @EnvironmentObject private var prefs: Prefs
    @Environment(\.dismiss) private var dismiss
    @State private var user = ""
    @State private var pass = ""
    @State private var info = ""

    var body: some View {
        NavigationStack {
            Form {
                Section("PC en la LAN") {
                    TextField("http://192.168.x.x:8787", text: $prefs.baseUrl)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                    TextField("usuario", text: $user)
                        .textInputAutocapitalization(.never)
                    SecureField("clave", text: $pass)
                    Button("Entrar") {
                        Task {
                            do {
                                let name = try await Brain(prefs: prefs).login(user: user, password: pass)
                                info = "Hola, \(name)"
                                prefs.solo = false
                            } catch {
                                info = error.localizedDescription
                            }
                        }
                    }
                    Toggle("Modo solo (sin PC)", isOn: $prefs.solo)
                    if prefs.loggedIn {
                        Button("Salir", role: .destructive) { prefs.logout() }
                    }
                }
                if !info.isEmpty {
                    Section { Text(info) }
                }
            }
            .navigationTitle("Perfil")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cerrar") { dismiss() }
                }
            }
        }
    }
}
