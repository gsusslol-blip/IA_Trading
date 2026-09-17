# Ilaria iOS

Cliente móvil con la misma superficie de comandos que Android (`phone_hands` + modo solo).

## Requisitos

- macOS + Xcode 15+
- [XcodeGen](https://github.com/yonaskolb/XcodeGen) (opcional pero recomendado)

## Generar el `.xcodeproj`

```bash
cd ios
brew install xcodegen   # si falta
xcodegen generate
open Ilaria.xcodeproj
```

Sin XcodeGen: en Xcode → *File → New → Project → App*, bundle `app.gsuss.ilaria`, y arrastrá los `.swift` + `Info.plist` de `Ilaria/`.

## Uso

1. PC con Ilaria en la misma Wi‑Fi (`run.bat`, puerto 8787).
2. En la app: **Perfil** → URL `http://IP-DE-LA-PC:8787` → Entrar con tu usuario.
3. O **Modo solo** para comandos locales sin PC.

La app manda `client: "ios"`; el backend encola `phone_actions` igual que Android.

En **Perfil → Buscar PC en Wi‑Fi** la app manda UDP `ILARIA_IOS_DISCOVER` al puerto **8788**
(misma LAN que Android). La PC responde `ILARIA_IOS_SERVER_ACK` + URL del HUD.

### Red local (crítico en device/simulador)

`Info.plist` ya declara:
- `NSLocalNetworkUsageDescription` — iOS muestra el prompt de red local
- `NSBonjourServices` → `_ilaria._udp` — desbloquea el diálogo en builds recientes

Sin aceptar ese permiso, el broadcast UDP al 8788 no sale. En la consola de la PC tenés que ver:
`[UDP LAN] Cliente iOS (SwiftUI) reconocido en 192.168.x.x`

## Límites de Apple

- Volumen / bloqueo de pantalla: iOS no deja a apps de terceros (usa botones del sistema).
- Captura: lateral + volumen arriba.
- Algunas URLs de Ajustes (`App-Prefs`) pueden no abrir en iOS reciente → cae a Ajustes de la app.
