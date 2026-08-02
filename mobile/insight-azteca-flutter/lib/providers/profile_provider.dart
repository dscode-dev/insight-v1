import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/profile.dart';
import '../services/services_providers.dart';

final profileBundleProvider = FutureProvider.autoDispose<ProfileBundle>(
  (ref) => ref.watch(profileServiceProvider).bundle(),
);
