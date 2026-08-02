# Azteca (Flutter)

Native Flutter client for Insight — social intelligence platform.
Replaces the Next.js PWA. Same Atrium gateway, different rendering layer.

## Why Flutter

The product is social-first (Threads / X / Reddit shape, not dashboards).
A WebView-wrapped PWA adds layers (Next → React → SW → WebView) without
delivering native UX. Flutter is one rendering layer with first-class
gestures, animation, and platform integration.

## Stack (locked)

- **Flutter** + Material 3
- **Riverpod** (no BLoC / GetX / MobX) — `flutter_riverpod`, `hooks_riverpod`, `riverpod_generator`
- **GoRouter** for navigation
- **Dio** for HTTP (Atrium gateway)
- **Freezed** + `json_serializable` for models
- **Flutter Hooks** when ergonomic
- **Responsive Framework** for breakpoints
- **flutter_secure_storage** for tokens (replaces `localStorage`)
- **dart:io HttpClient** for SSE realtime
- **google_fonts** (Inter)

## Architecture

```
lib/
├── main.dart         entry
├── app.dart          MaterialApp.router + theme + responsive
├── core/             env, errors, api mode, logger, token storage
├── shared/           extensions, format helpers, pt-BR strings
├── theme/            colors, typography, spacing, radii, motion
├── routing/          GoRouter + shell + auth guard
├── services/         atrium client + per-domain services
├── models/           Freezed wire models
├── providers/        Riverpod (AsyncNotifier, StreamProvider, etc.)
├── widgets/          design-system primitives (no domain)
├── mock/             mock provider + fixtures
└── features/
    ├── auth/         login + register + AuthForm
    ├── home/         feed + Quick Pulse + Composer
    ├── live/         live matches + match detail
    ├── radar/        intelligence discovery
    ├── hub/          communities + discussions
    └── profile/      identity + reputation
```

## Running

```bash
flutter pub get
dart run build_runner build --delete-conflicting-outputs
flutter run -d <device>
```

API mode is chosen at compile-time:

```bash
flutter run --dart-define=API_MODE=mock           # default
flutter run --dart-define=API_MODE=atrium \
            --dart-define=ATRIUM_BASE_URL=http://sanninjiraiya.lab:30080
```

## Design system

See `lib/theme/` — five token files (colors, typography, spacing, radii,
motion) and one ThemeData composition. Do not hard-code colors or
spacing in widgets; always pull from `context.ds`.

Identity: **inteligente, analítica, social, esportiva, premium, moderna.**
Not a Threads clone — semantic colors are visible (confidence high = green,
not grey), typography is comfortable, and motion is restrained.

## What survives from the Next.js Azteca

- Wire format (1:1 translation to Freezed models)
- Atrium client semantics (Bearer + 401 refresh + clear-on-double-401)
- Service-per-domain layout
- API-mode switch (mock vs atrium)
- pt-BR copy (centralised in `shared/strings/pt_br.dart`)
- Stage 5b/6 product decisions (unified feed, agent posts with side stripe,
  MatchEmbed without card chrome)

## What does NOT survive

- All React components (rewritten as widgets)
- Tailwind + globals.css (replaced by ThemeData)
- TanStack Query (replaced by Riverpod)
- Zustand + localStorage (replaced by Riverpod + flutter_secure_storage)
- PWA manifest / service worker (Flutter is native)
- Hairline-divider Threads clone aesthetic (new visual identity)
- BottomSheet DOM (Material 3 `showModalBottomSheet`)
- IntersectionObserver-based infinite scroll (native scroll controllers)
