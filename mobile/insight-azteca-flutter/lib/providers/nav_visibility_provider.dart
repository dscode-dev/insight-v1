import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Visibility of the floating bottom nav.
///
/// Driven by any scroll-aware screen — Home, Live, Hub, etc. — through
/// the helper `NavVisibilityScrollListener` (lib/widgets/nav_scroll_listener.dart).
/// Anything that wants the nav out of the way (full-screen sheets, the
/// composer mid-typing) flips `state = false` and restores on dismiss.
///
/// Default: visible. Splash + auth flows live above the shell so the
/// initial state never matters there.
final navVisibilityProvider = StateProvider<bool>((_) => true);


/// Sprint 2 (Part 5) — Home-tab re-tap broadcast. The shell bumps the
/// tick whenever the user taps Home while ALREADY on the Home root;
/// HomeScreen listens and runs refresh + scroll-to-top. A counter (not
/// a bool) so consecutive re-taps always fire.
final homeRetapTickProvider = StateProvider<int>((_) => 0);
