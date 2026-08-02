// Splash screen shown during `AuthStatus.hydrating`.
//
// Visual contract:
//   * ONE fullscreen flat background (#0A0E1A) — identical to the
//     native launch screen on both platforms, so the native→Flutter
//     hand-off is seamless (no second background, no size jump, no
//     flash). The native mark is sized to match this logo (~128dp).
//   * ONLY the official transparent Insight mark, never stretched:
//     the asset is square and rendered BoxFit.contain in a square box,
//     so aspect ratio is preserved on every screen.
//   * Premium entrance: the mark fades + scales up gently while a soft
//     brand-signal glow breathes behind it; a staggered three-dot
//     pulse sits below as the loading affordance (no stock spinner).
//   * Responsive: logo size derives from the shortest screen side,
//     clamped, so it reads calm on iPhone, Pro Max and 11"/13" iPads.
import 'package:flutter/material.dart';

import '../../shared/extensions/build_context_x.dart';

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen>
    with TickerProviderStateMixin {
  // One-shot entrance: fade + scale-up of the mark.
  late final AnimationController _entry = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 900),
  )..forward();

  late final Animation<double> _fadeIn = CurvedAnimation(
    parent: _entry,
    curve: Curves.easeOutCubic,
  );

  // 0.86 → 1.0 with a soft overshoot — intentional, not bouncy.
  late final Animation<double> _scaleIn = Tween<double>(begin: 0.86, end: 1)
      .animate(CurvedAnimation(parent: _entry, curve: Curves.easeOutBack));

  // Continuous ambient loop: drives the breathing glow + the dots.
  late final AnimationController _loop = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 2600),
  )..repeat();

  @override
  void dispose() {
    _entry.dispose();
    _loop.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // Single source of truth for the boot background — kept in sync
    // with flutter_native_splash + the iOS storyboard.
    const background = Color(0xFF0A0E1A);
    final glowColor = context.ds.signal;

    final shortestSide = MediaQuery.sizeOf(context).shortestSide;
    // ~26% of the shortest side, clamped: presence on small phones,
    // calm on iPads. Matches the native mark (~128dp).
    final logoSize = (shortestSide * 0.26).clamp(108.0, 156.0).toDouble();

    return ColoredBox(
      color: background,
      child: Stack(
        fit: StackFit.expand,
        children: [
          // Mark + breathing glow — dead center.
          Center(
            child: FadeTransition(
              opacity: _fadeIn,
              child: ScaleTransition(
                scale: _scaleIn,
                child: SizedBox(
                  width: logoSize * 2.4,
                  height: logoSize * 2.4,
                  child: Stack(
                    alignment: Alignment.center,
                    children: [
                      // Soft signal-blue glow that breathes behind the
                      // mark. Subtle — it lifts the logo off the flat
                      // background without reading as a "card".
                      AnimatedBuilder(
                        animation: _loop,
                        builder: (context, _) {
                          final wave = _breathe(_loop.value);
                          return Container(
                            width: logoSize * (1.7 + wave * 0.25),
                            height: logoSize * (1.7 + wave * 0.25),
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              gradient: RadialGradient(
                                colors: [
                                  glowColor.withValues(
                                    alpha: 0.10 + wave * 0.10,
                                  ),
                                  glowColor.withValues(alpha: 0),
                                ],
                              ),
                            ),
                          );
                        },
                      ),
                      Semantics(
                        label: 'Insight',
                        image: true,
                        child: Image.asset(
                          'assets/image/insight-logo-transparent.png',
                          width: logoSize,
                          height: logoSize,
                          fit: BoxFit.contain,
                          filterQuality: FilterQuality.high,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
          // Loader band below the centered mark.
          Align(
            alignment: const Alignment(0, 0.4),
            child: FadeTransition(
              opacity: _fadeIn,
              child: _PulseDots(loop: _loop),
            ),
          ),
        ],
      ),
    );
  }
}

/// Maps loop value [0,1] to a smooth 0→1→0 breathing wave.
double _breathe(double t) =>
    Curves.easeInOut.transform(t < 0.5 ? t * 2 : (1 - t) * 2);

/// Three softly pulsing dots — shares the ambient loop controller.
class _PulseDots extends StatelessWidget {
  const _PulseDots({required this.loop});

  final Animation<double> loop;

  @override
  Widget build(BuildContext context) {
    final color = context.ds.signal;
    return AnimatedBuilder(
      animation: loop,
      builder: (context, _) {
        return Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (var i = 0; i < 3; i++) ...[
              if (i > 0) const SizedBox(width: 8),
              _dot(i, color),
            ],
          ],
        );
      },
    );
  }

  Widget _dot(int index, Color color) {
    // Staggered pulse: each dot trails the previous by ~0.16 of the loop.
    final phase = (loop.value - index * 0.16) % 1.0;
    final wave = _breathe(phase);
    return Container(
      width: 6,
      height: 6,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        // Quiet white base, brightening toward the brand signal at peak.
        color: Color.lerp(
          Colors.white.withValues(alpha: 0.20),
          color.withValues(alpha: 0.95),
          wave,
        ),
      ),
    );
  }
}
