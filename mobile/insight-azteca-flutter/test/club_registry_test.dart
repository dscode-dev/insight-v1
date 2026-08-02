// Club Registry (Azteca) — canonical resolution + bundled logo asset.
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/services.dart' show rootBundle;

import 'package:azteca/clubs/club_registry.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late ClubRegistry reg;

  setUpAll(() async {
    // Load the real bundled registry through the test asset bundle.
    final raw = await rootBundle.loadString('assets/clubs/logo_manifest.json');
    reg = ClubRegistry.instance..ingest(raw);
  });

  test('registry loads a substantial club set', () {
    expect(reg.isLoaded, isTrue);
    expect(reg.count, greaterThan(50));
    expect(reg.version, isNotEmpty);
  });

  test('canonical resolution: Man City variants → manchester_city', () {
    for (final q in const [
      'Manchester City',
      'Man City',
      'Manchester City FC',
      'manchester_city',
      'MCI',
    ]) {
      expect(reg.resolve(q), 'manchester_city', reason: 'query: $q');
    }
  });

  test('accent + punctuation folding', () {
    expect(reg.resolve('Atlético Mineiro'), 'atletico_mineiro');
    expect(reg.resolve('Flamengo'), 'flamengo');
    expect(reg.resolve('CR Flamengo'), 'flamengo');
  });

  test('lookup carries the bundled logo asset path', () {
    final club = reg.lookup('Real Madrid CF');
    expect(club, isNotNull);
    expect(club!.clubId, 'real_madrid');
    expect(club.logoAsset, 'assets/clubs/real/real_madrid.png');
  });

  test('unknown club resolves to null (badge falls back to initials)', () {
    expect(reg.resolve('Some Unlisted FC'), isNull);
    expect(reg.lookup(''), isNull);
  });
}
