/// Tempo relativo curto em pt-BR — "agora", "5s", "5min", "2h", "3d".
///
/// Width-optimised for mobile (no spaces inside the unit).
String relativeTime(DateTime when, {DateTime? now}) {
  final n = now ?? DateTime.now();
  final diffSec = n.difference(when).inSeconds;
  if (diffSec < 30) return 'agora';
  if (diffSec < 60) return '${diffSec}s';
  final min = diffSec ~/ 60;
  if (min < 60) return '${min}min';
  final h = min ~/ 60;
  if (h < 24) return '${h}h';
  final d = h ~/ 24;
  return '${d}d';
}
