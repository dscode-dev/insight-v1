import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/competition.dart';
import '../services/competition_service.dart';
import '../services/gateway_client.dart';

/// Featured Competitions Rail providers (AZTECA-HOME-A). Backend-only — no mock.

final competitionServiceProvider = Provider<GatewayCompetitionService>(
  (ref) => GatewayCompetitionService(ref.watch(gatewayDioProvider)),
);

/// The competitions for the Home rail, exactly as ordered by insight-social
/// (featured → priority → display_order → alphabetical). The widget renders
/// this list in order and never re-sorts it.
final featuredCompetitionsProvider =
    FutureProvider.autoDispose<List<Competition>>(
  (ref) => ref.watch(competitionServiceProvider).highlights(),
);
