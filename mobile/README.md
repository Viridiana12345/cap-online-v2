# CAP Online Mobile

Aplicación móvil separada del portal web, construida con Vite + Capacitor y conectada a `/api/v1/` del mismo Django/PostgreSQL.

## Vista previa
```powershell
npm install
npm run dev
```
Abre `http://127.0.0.1:5173` con Django ejecutándose en `127.0.0.1:8000`.

## Android
```powershell
npm install
npx cap add android
npm run android
```
En Android Emulator la API predeterminada es `http://10.0.2.2:8000/api/v1`.

## Biometría
La implementación usa `@aparajita/capacitor-biometric-auth`. Después del primer login se conserva el token de la app y el siguiente acceso puede solicitar biometría nativa. Android usa la biometría disponible; iOS usa Touch ID/Face ID según el dispositivo.

## iOS
```bash
npx cap add ios
npm run ios
```
La compilación iOS requiere macOS/Xcode. Para Face ID agrega `NSFaceIDUsageDescription` en el `Info.plist` del proyecto iOS con una explicación como: `CAP Online usa Face ID para proteger el acceso a tu sesión.`

## Nota de seguridad
`@capacitor/preferences` es suficiente para el prototipo académico, pero para una publicación real el token debe guardarse en Keychain/Keystore mediante almacenamiento seguro nativo.
