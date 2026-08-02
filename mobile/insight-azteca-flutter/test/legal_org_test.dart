// AZTECA-QUALITY-A — legal/store-facing organization is AllBlue-Labs.
import 'package:flutter_test/flutter_test.dart';
import 'package:azteca/core/legal.dart';

void main() {
  test('data controller + liability name AllBlue-Labs, not KonohaLabs', () {
    final privacyBodies =
        kPrivacyDocument.sections.map((s) => s.body).join('\n');
    final termsBodies = kTermsDocument.sections.map((s) => s.body).join('\n');

    expect(privacyBodies, contains('AllBlue-Labs'),
        reason: 'privacy data-controller must name AllBlue-Labs');
    expect(termsBodies, contains('AllBlue-Labs'),
        reason: 'terms liability clause must name AllBlue-Labs');
    // The legal OWNER text must not read KonohaLabs (infra hosts are separate).
    expect(privacyBodies, isNot(contains('KonohaLabs')));
    expect(termsBodies, isNot(contains('KonohaLabs')));
  });

  test('material ownership change bumped the accepted terms version', () {
    expect(kTermsVersion, '1.2');
    expect(kPrivacyVersion, '1.2');
  });
}
