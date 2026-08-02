import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/hub.dart';
import '../services/services_providers.dart';

/// Active segment selector for the Hub. "Em alta" is the most useful
/// default — gives newcomers something populated before they've followed
/// anything.
final hubSegmentProvider = StateProvider<HubSegment>((_) => HubSegment.hot);

final hubBundleProvider = FutureProvider.autoDispose<HubBundle>((ref) {
  final segment = ref.watch(hubSegmentProvider);
  return ref.watch(hubServiceProvider).bundle(segment: segment);
});

/// Detail for a single community. Null when the id doesn't match — the
/// screen renders a "community não encontrada" state instead of throwing.
final communityDetailProvider =
    FutureProvider.autoDispose.family<CommunityDetail?, String>(
  (ref, id) => ref.watch(hubServiceProvider).communityDetail(id),
);
