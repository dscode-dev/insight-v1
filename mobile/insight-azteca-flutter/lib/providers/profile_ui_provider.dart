import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Selected Profile section, keyed per profile (`'me'` for the logged-in
/// profile, or a userId for a public one) so each profile remembers its own
/// tab. 0 = Atividade, 1 = Comunidades, 2 = Estatísticas.
///
/// Deliberately NOT autoDispose so the choice survives navigating away and back
/// within the session (AZTECA-PROFILE-A — state preservation). Pairs with an
final profileSectionIndexProvider =
    StateProvider.family<int, String>((ref, profileKey) => 0);

/// The shared Sports Profile tab labels (Stage 5).
const kProfileTabs = <String>['Atividade', 'Comunidades', 'Estatísticas'];
